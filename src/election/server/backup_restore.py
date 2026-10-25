"""Restore a verified server snapshot into an explicitly separate disposable test schema."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, create_engine, delete, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from election.server.backups import _file_hash, _private_manifest, _source_hash
from election.server.models import AuditEvent, LoginSession
from election.server.mysql_backup_tools import BackupToolError, dump_mysql, restore_mysql


class RestoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELECTION_", env_file=".env", extra="ignore")
    database_url: str = Field(repr=False)
    restore_database_url: str = Field(repr=False)


class RestoreError(RuntimeError):
    def __init__(self, code: str, *, phase: str | None = None) -> None:
        self.code, self.phase = code, phase
        super().__init__(code)


def _warning(code: str, record: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "status": record["status"],
                "warning_code": code,
                "operation_id": record["operation_id"],
            }
        ),
        file=sys.stderr,
    )


def _private_file(path: Path) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RestoreError("restore_manifest_not_private")
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise RestoreError("restore_directory_not_private")
    return path


def restore(manifest_path: Path, target_schema: str, container: str | None) -> dict[str, str]:
    settings = RestoreSettings()
    active_url, target_url = (
        make_url(settings.database_url),
        make_url(settings.restore_database_url),
    )
    if (
        active_url.drivername != "mysql+pymysql"
        or target_url.drivername != "mysql+pymysql"
        or re.fullmatch(r"[A-Za-z0-9_$]{1,64}", target_schema) is None
        or not target_schema.endswith("_test")
        or target_url.database != target_schema
        or target_schema == active_url.database
    ):
        raise RestoreError("restore_target_not_separate_test_schema")
    manifest_path = _private_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RestoreError("restore_manifest_invalid")
    if manifest.get("format") != "election-mysql-backup-v1" or manifest.get("status") != "complete":
        raise RestoreError("restore_manifest_incomplete")
    if target_schema == manifest["source_schema"]:
        raise RestoreError("restore_target_not_separate_test_schema")
    backup_id = str(UUID(manifest["backup_id"]))
    if manifest["artifact"] != backup_id + ".sql":
        raise RestoreError("restore_artifact_name_invalid")
    artifact = _private_file(manifest_path.parent / manifest["artifact"])
    if (
        artifact.stat().st_size != manifest["size_bytes"]
        or _file_hash(artifact) != manifest["sha256"]
    ):
        raise RestoreError("restore_artifact_hash_mismatch")
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    expected_revisions = sorted(ScriptDirectory.from_config(config).get_heads())
    if sorted(manifest["schema_revisions"]) != expected_revisions:
        raise RestoreError("restore_schema_version_mismatch")
    if manifest["application_source_sha256"] != _source_hash():
        raise RestoreError("restore_application_source_mismatch")

    directory = manifest_path.parent / "restore-jobs"
    directory.mkdir(mode=0o700, exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise RestoreError("restore_directory_not_private")
    operation_id = str(uuid4())
    lock = directory / (target_schema + ".lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RestoreError("restore_target_busy") from None
    os.close(descriptor)
    record: dict[str, Any] = {
        "operation_id": operation_id,
        "backup_id": backup_id,
        "source_schema": manifest["source_schema"],
        "target_schema": target_schema,
        "artifact_sha256": manifest["sha256"],
        "manifest_sha256": _file_hash(manifest_path),
        "started_at": datetime.now(UTC).isoformat(),
        "status": "started",
        "phase": "validated",
    }
    try:
        target_engine = create_engine(target_url)
        guard: Connection | None = None
        lock_name = "election-backup-" + hashlib.sha256(target_schema.encode()).hexdigest()[:40]
        try:
            guard = target_engine.connect()
            acquired = guard.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name})
            if acquired != 1:
                raise RestoreError("restore_target_busy")
            # Connecting by an explicit existing database also refuses absent schemas.
            with target_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                tables = inspect(connection).get_table_names()
                record["prior_schema_revisions"] = (
                    list(connection.scalars(text("SELECT version_num FROM alembic_version")))
                    if "alembic_version" in tables
                    else []
                )
            prior = directory / (operation_id + ".prior-target.sql")
            record["backup_client_version"] = dump_mysql(
                settings.restore_database_url, prior, container=container
            )
            record["prior_target_artifact"] = prior.name
            record["prior_target_sha256"] = _file_hash(prior)
            record["phase"] = "target_preserved"
            _private_manifest(directory / (operation_id + ".started.json"), record)
            record["phase"] = "importing"
            record["restore_client_version"] = restore_mysql(
                settings.restore_database_url, artifact, container=container
            )
            record["phase"] = "imported"
            with target_engine.connect() as connection:
                restored = sorted(
                    connection.scalars(text("SELECT version_num FROM alembic_version"))
                )
            if restored != expected_revisions:
                raise RestoreError("restored_schema_version_mismatch")
            record["phase"] = "schema_verified"
            with Session(target_engine) as db:
                db.execute(delete(LoginSession))
                db.add(
                    AuditEvent(
                        actor_id=None,
                        action="backup_restored_to_test",
                        occurred_at=datetime.now(UTC).replace(tzinfo=None),
                        details={
                            "backup_id": backup_id,
                            "operation_id": operation_id,
                            "source_schema": manifest["source_schema"],
                            "target_schema": target_schema,
                            "sha256": manifest["sha256"],
                        },
                    )
                )
                db.commit()
            record.update(
                status="succeeded",
                phase="recovered",
                restored_schema_revisions=restored,
                copied_sessions_invalidated=True,
            )
        finally:
            if guard is not None:
                try:
                    guard.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                    guard.close()
                except SQLAlchemyError:
                    _warning("restore_database_lease_cleanup_unavailable", record)
            target_engine.dispose()
    except (BackupToolError, RestoreError, OSError, SQLAlchemyError) as error:
        code = (
            error.code
            if isinstance(error, (BackupToolError, RestoreError))
            else "restore_io_or_database_failed"
        )
        incomplete = record["phase"] in ("importing", "imported", "schema_verified")
        record.update(status="incomplete" if incomplete else "failed", error_code=code)
        raise RestoreError(code, phase=record["phase"]) from None
    finally:
        record["finished_at"] = datetime.now(UTC).isoformat()
        try:
            _private_manifest(directory / (operation_id + ".result.json"), record)
        except OSError:
            # The data/audit commit is already acknowledged. A local receipt
            # failure must not turn confirmed recovery into a reported failure.
            _warning("restore_result_manifest_unavailable", record)
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            _warning("restore_lease_cleanup_unavailable", record)
    return {
        "status": "succeeded",
        "source_schema": manifest["source_schema"],
        "target_schema": target_schema,
        "backup_id": backup_id,
        "sha256": manifest["sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-schema", required=True)
    parser.add_argument("--mysql-container")
    args = parser.parse_args()
    try:
        result = restore(args.manifest, args.target_schema, args.mysql_container)
    except (
        RestoreError,
        BackupToolError,
        OSError,
        SQLAlchemyError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (BackupToolError, RestoreError))
            else "restore_configuration_or_data_invalid"
        )
        phase = error.phase if isinstance(error, RestoreError) else None
        incomplete = phase in ("importing", "imported", "schema_verified")
        print(
            json.dumps(
                {
                    "status": "incomplete" if incomplete else "failed",
                    "error_code": code,
                    **({"phase": phase} if phase else {}),
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
