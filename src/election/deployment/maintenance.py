"""Explicit offline schema maintenance with a durable startup interlock."""

import fcntl
import getpass
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from election.deployment.configuration import API_UID, DeploymentError, private_write
from election.manage import bootstrap_account
from election.private_paths import private_directory, private_file, private_file_descriptor
from election.server.backups import BackupSettings, _file_hash, _private_manifest, _source_hash
from election.server.config import Settings
from election.server.db import make_engine
from election.server.models import Account
from election.server.mysql_backup_tools import BackupToolError, dump_mysql
from election.server.readiness import require_schema


def migration_config() -> Config:
    root = Path(__file__).resolve().parents[3]
    return Config(str(root / "alembic.ini"))


def state_directory() -> Path:
    directory = Path(os.environ["ELECTION_DEPLOY_STATE_DIR"])
    if not private_directory(directory):
        raise DeploymentError("deployment_state_missing_or_unsafe")
    return directory


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def operator_lease() -> Iterator[None]:
    """Serialize host administration; a crash releases the lease, never the interlock."""
    descriptor = os.open(
        state_directory() / "operator.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        if not private_file_descriptor(descriptor):
            raise DeploymentError("operator_lease_not_private")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError("deployment_administration_busy") from None
        yield
    finally:
        os.close(descriptor)


def _state(value: dict[str, Any]) -> None:
    path = state_directory() / "maintenance.json"
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".maintenance-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if os.geteuid() == 0:
            os.chown(temporary, API_UID, API_UID)
        temporary.replace(path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def initialize(username: str, display_name: str) -> dict[str, str]:
    marker = state_directory() / "initialized.json"
    engine = make_engine(Settings().database_url)
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
        if not tables:
            if marker.exists():
                raise DeploymentError("initialized_database_is_empty")
            command.upgrade(migration_config(), "head")
        require_schema(engine)
        with Session(engine) as database:
            existing = database.scalar(select(Account.id).limit(1))
        if existing is None:
            password = getpass.getpass("Temporary administrator password (12–128 characters): ")
            if password != getpass.getpass("Confirm temporary password: "):
                raise DeploymentError("administrator_passwords_differ")
            bootstrap_account(Settings().database_url, username, display_name, password)
        if not marker.exists():
            private_write(
                marker, json.dumps({"initialized_at": datetime.now(UTC).isoformat()}), uid=API_UID
            )
        return {"status": "initialized", "administrator": "existing" if existing else "created"}
    finally:
        engine.dispose()


def reserve() -> dict[str, str]:
    """Interlock startup before a portable operator workflow stops the API."""
    path = state_directory() / "maintenance.json"
    try:
        private_write(
            path,
            json.dumps(
                {
                    "operation_id": str(uuid4()),
                    "phase": "reserved",
                    "started_at": datetime.now(UTC).isoformat(),
                }
            )
            + "\n",
            uid=API_UID,
        )
    except FileExistsError:
        raise DeploymentError("maintenance_already_pending") from None
    _sync_directory(path.parent)
    return {"status": "maintenance_reserved"}


def backup(*, image_id: str | None = None) -> dict[str, str]:
    """The shell entry point stops the API before this offline operation."""
    state = state_directory() / "maintenance.json"
    if state.exists():
        previous = json.loads(state.read_text())
        if previous.get("phase") not in {"backup_failed", "reserved"}:
            raise DeploymentError("maintenance_already_pending")
    operation = str(uuid4())
    record: dict[str, Any] = {
        "operation_id": operation,
        "phase": "backup_started",
        "started_at": datetime.now(UTC).isoformat(),
        "image_id": image_id,
    }
    _state(record)
    directory = Path(os.environ["ELECTION_BACKUP_DIRECTORY"])
    engine: Engine | None = None
    try:
        if not private_directory(directory):
            raise DeploymentError("backup_directory_not_private")
        engine = make_engine(Settings().database_url)
        with engine.connect() as connection:
            lock = (
                "election-backup-"
                + hashlib.sha256(str(engine.url.database).encode()).hexdigest()[:40]
            )
            if connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock}) != 1:
                raise DeploymentError("backup_busy")
            try:
                if connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema=DATABASE() AND table_type='BASE TABLE' "
                        "AND engine<>'InnoDB'"
                    )
                ):
                    raise DeploymentError("backup_nontransactional_tables")
                revisions = list(
                    connection.scalars(text("SELECT version_num FROM alembic_version"))
                )
                started = datetime.now(UTC).isoformat()
                artifact = directory / (operation + ".sql")
                version = dump_mysql(
                    Settings().database_url,
                    artifact,
                    container=None,
                    client_binary=BackupSettings().mysqldump_binary,
                )
                manifest = {
                    "format": "election-mysql-backup-v1",
                    "status": "complete",
                    "backup_id": operation,
                    "request_id": operation,
                    "artifact": artifact.name,
                    "source_schema": engine.url.database,
                    "schema_revisions": revisions,
                    "application_source_sha256": _source_hash(),
                    "mysqldump_version": version,
                    "mysql_server_version": str(connection.scalar(text("SELECT VERSION()"))),
                    "sha256": _file_hash(artifact),
                    "size_bytes": artifact.stat().st_size,
                    "cutoff_start": started,
                    "cutoff_end": datetime.now(UTC).isoformat(),
                    "cutoff_semantics": (
                        "Offline InnoDB snapshot; API writes stopped before migration."
                    ),
                }
                _private_manifest(directory / (operation + ".manifest.json"), manifest)
                record.update(
                    phase="backed_up",
                    backup_id=operation,
                    previous_source_sha256=_source_hash(),
                    schema_revisions=revisions,
                )
                _state(record)
            finally:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock})
    except Exception as error:
        record.update(
            phase="backup_failed",
            error_code=(
                error.code
                if isinstance(error, BackupToolError)
                else str(error)
                if isinstance(error, DeploymentError)
                else "backup_failed"
            ),
        )
        _state(record)
        raise
    finally:
        if engine is not None:
            engine.dispose()
        record["finished_at"] = datetime.now(UTC).isoformat()
        receipts = directory if private_directory(directory) else state_directory()
        _private_manifest(receipts / (operation + ".maintenance.json"), record)
    return {"status": "backed_up", "backup_id": operation}


def migrate() -> dict[str, str]:
    path = state_directory() / "maintenance.json"
    if not private_file(path):
        raise DeploymentError("pre_migration_backup_required")
    record = json.loads(path.read_text())
    if record.get("phase") != "backed_up":
        raise DeploymentError("pre_migration_backup_required")
    backup_id = str(UUID(record["backup_id"]))
    directory = Path(os.environ["ELECTION_BACKUP_DIRECTORY"])
    manifest_path = directory / (backup_id + ".manifest.json")
    artifact = directory / (backup_id + ".sql")
    if not private_file(manifest_path) or not private_file(artifact):
        raise DeploymentError("pre_migration_backup_unavailable")
    manifest = json.loads(manifest_path.read_text())
    engine = make_engine(Settings().database_url)
    try:
        with engine.connect() as connection:
            revisions = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
        if (
            manifest.get("format") != "election-mysql-backup-v1"
            or manifest.get("status") != "complete"
            or manifest.get("backup_id") != backup_id
            or manifest.get("request_id") != record["operation_id"]
            or manifest.get("artifact") != artifact.name
            or manifest.get("application_source_sha256") != record["previous_source_sha256"]
            or manifest["source_schema"] != engine.url.database
            or sorted(manifest["schema_revisions"]) != sorted(revisions)
            or sorted(manifest["schema_revisions"]) != sorted(record["schema_revisions"])
            or manifest["sha256"] != _file_hash(artifact)
            or manifest["size_bytes"] != artifact.stat().st_size
        ):
            raise DeploymentError("pre_migration_backup_mismatch")
        record["phase"] = "migrating"
        _state(record)
        command.upgrade(migration_config(), "head")
        record.update(
            phase="migrated",
            schema_revisions=require_schema(engine, allow_maintenance=True),
            target_source_sha256=_source_hash(),
        )
        _state(record)
        _private_manifest(directory / (backup_id + ".migrated.json"), record)
        return {"status": "migrated", "backup_id": backup_id}
    finally:
        engine.dispose()


def finish() -> dict[str, str]:
    path = state_directory() / "maintenance.json"
    if not private_file(path):
        raise DeploymentError("maintenance_not_pending")
    record = json.loads(path.read_text())
    if record.get("phase") != "migrated" or record.get("target_source_sha256") != _source_hash():
        raise DeploymentError("maintenance_not_verified")
    engine = make_engine(Settings().database_url)
    try:
        require_schema(engine, allow_maintenance=True)
        directory = Path(os.environ["ELECTION_BACKUP_DIRECTORY"])
        _private_manifest(
            directory / (record["backup_id"] + ".finished.json"),
            {
                **record,
                "phase": "finished",
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
        path.unlink()
        _sync_directory(path.parent)
        return {"status": "maintenance_complete"}
    finally:
        engine.dispose()


def prepare_test_schema(schema: str, *, restore_target: bool) -> dict[str, str]:
    import re

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,58}_test", schema):
        raise DeploymentError("separate_test_schema_required")
    config = Path(os.environ["ELECTION_ENV_FILE"]).parent
    registry = config / "test-targets.json"
    targets: list[str] = json.loads(registry.read_text()) if registry.exists() else []
    url = make_url(Settings().database_url)
    root_password = Path(
        os.environ.get("ELECTION_MYSQL_ROOT_PASSWORD_FILE", str(config / "mysql-root-password"))
    ).read_text()
    engine = create_engine(url.set(username="root", password=root_password, database=None))
    try:
        with engine.begin() as connection:
            exists = connection.scalar(
                text("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=:schema"),
                {"schema": schema},
            )
            if exists and schema not in targets:
                raise DeploymentError("test_schema_already_exists")
            if not exists:
                connection.execute(text(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4"))
                connection.execute(text(f"GRANT ALL ON `{schema}`.* TO 'election'@'%'"))
                targets.append(schema)
                # This record contains names only; never source/target credentials.
                temporary = config / (".test-targets-" + uuid4().hex)
                private_write(temporary, json.dumps(targets))
                temporary.replace(registry)
    finally:
        engine.dispose()
    if restore_target:
        destination = config / "restore.env"
        if destination.exists():
            raise DeploymentError("restore_configuration_already_exists")
        private_write(
            destination,
            "ELECTION_RESTORE_DATABASE_URL="
            + url.set(database=schema).render_as_string(hide_password=False)
            + "\n",
        )
        server_configuration = (config / "server.env").read_text()
        lines = [
            "ELECTION_DATABASE_URL="
            + url.set(database=schema).render_as_string(hide_password=False)
            if line.startswith("ELECTION_DATABASE_URL=")
            else line
            for line in server_configuration.splitlines()
        ]
        private_write(config / "restore-server.env", "\n".join(lines) + "\n", uid=API_UID)
    return {"status": "test_schema_ready", "schema": schema}
