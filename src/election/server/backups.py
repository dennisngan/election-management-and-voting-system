"""Administrator backup requests use protected server-side MySQL snapshots."""

import hashlib
import json
import os
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from election.server.backup_models import ServerBackup
from election.server.models import Account, AuditEvent
from election.server.mysql_backup_tools import BackupToolError, dump_mysql
from election.server.polling import as_utc


class BackupSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELECTION_", env_file=".env", extra="ignore")
    backup_directory: Path = Path(".runtime/backups")
    mysql_container: str | None = None
    mysqldump_binary: str = "mysqldump"


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


def backup_view(row: ServerBackup) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "status": row.status,
        "requested_at": as_utc(row.requested_at),
        "completed_at": as_utc(row.completed_at),
        "cutoff_start": as_utc(row.cutoff_start),
        "cutoff_end": as_utc(row.cutoff_end),
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "error_code": row.error_code,
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_hash() -> str:
    package = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".qml"):
            digest.update(str(path.relative_to(package)).encode())
            digest.update(bytes.fromhex(_file_hash(path)))
    return digest.hexdigest()


def _private_manifest(path: Path, manifest: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as output:
        path.chmod(0o600)
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def backups_router(
    database: Callable[..., Any],
    administrator: Callable[..., Account],
    timestamp: Callable[[], datetime],
    engine: Engine,
) -> APIRouter:
    settings = BackupSettings()
    router = APIRouter(prefix="/api/backups", tags=["Server backups"])
    Database = Annotated[Session, Depends(database)]
    Administrator = Annotated[Account, Depends(administrator)]
    lock_name = (
        "election-backup-" + hashlib.sha256(str(engine.url.database).encode()).hexdigest()[:40]
    )

    @router.get("")
    def listing(db: Database, actor: Administrator) -> dict[str, Any]:
        rows = db.scalars(select(ServerBackup).order_by(ServerBackup.requested_at.desc()))
        return {"backups": [backup_view(row) for row in rows]}

    def perform(data: BackupRequest, db: Session, actor: Account) -> dict[str, Any]:
        previous = db.scalar(
            select(ServerBackup)
            .where(ServerBackup.request_id == str(data.request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if previous:
            if previous.actor_id != actor.id:
                raise HTTPException(409, detail={"code": "request_conflict"})
            return backup_view(previous)
        row = ServerBackup(
            id=str(uuid4()),
            request_id=str(data.request_id),
            actor_id=actor.id,
            status="running",
            requested_at=timestamp(),
            manifest_data={},
        )
        db.add(row)
        db.add(
            AuditEvent(
                actor_id=actor.id,
                action="backup_requested",
                occurred_at=timestamp(),
                details={"request_id": row.request_id, "backup_id": row.id},
            )
        )
        db.commit()
        try:
            directory = settings.backup_directory
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if stat.S_IMODE(directory.stat().st_mode) & 0o077:
                raise BackupToolError("backup_directory_not_private")
            nontransactional = db.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=DATABASE() AND table_type='BASE TABLE' AND engine<>'InnoDB'"
                )
            )
            if nontransactional:
                raise BackupToolError("backup_nontransactional_tables")
            revisions = list(db.scalars(text("SELECT version_num FROM alembic_version")))
            server_version = str(db.scalar(text("SELECT VERSION()")))
            row.cutoff_start = db.scalar(text("SELECT UTC_TIMESTAMP(6)"))
            db.commit()
            artifact = directory / (row.id + ".sql")
            version = dump_mysql(
                engine.url.render_as_string(hide_password=False),
                artifact,
                container=settings.mysql_container,
                client_binary=settings.mysqldump_binary,
            )
            row.cutoff_end = db.scalar(text("SELECT UTC_TIMESTAMP(6)"))
            row.sha256 = _file_hash(artifact)
            row.size_bytes = artifact.stat().st_size
            row.manifest_data = {
                "format": "election-mysql-backup-v1",
                "backup_id": row.id,
                "request_id": row.request_id,
                "artifact": artifact.name,
                "source_schema": engine.url.database,
                "schema_revisions": revisions,
                "application_source_sha256": _source_hash(),
                "mysql_server_version": server_version,
                "mysqldump_version": version,
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "cutoff_start": as_utc(row.cutoff_start),
                "cutoff_end": as_utc(row.cutoff_end),
                "cutoff_semantics": (
                    "InnoDB consistent snapshot began within this server-time interval; "
                    "maintenance DDL must not run during backup. "
                    "Completion audit follows the snapshot."
                ),
            }
            _private_manifest(directory / (row.id + ".manifest.json"), row.manifest_data)
            row.status = "succeeded"
            row.completed_at = timestamp()
            db.add(
                AuditEvent(
                    actor_id=actor.id,
                    action="backup_completed",
                    occurred_at=timestamp(),
                    details={
                        "request_id": row.request_id,
                        "backup_id": row.id,
                        "sha256": row.sha256,
                        "size_bytes": row.size_bytes,
                    },
                )
            )
        except (BackupToolError, OSError) as error:
            row.status = "failed"
            row.error_code = (
                error.code if isinstance(error, BackupToolError) else "backup_io_failed"
            )
            row.completed_at = timestamp()
            row.sha256 = None
            row.size_bytes = None
            db.add(
                AuditEvent(
                    actor_id=actor.id,
                    action="backup_failed",
                    occurred_at=timestamp(),
                    details={
                        "request_id": row.request_id,
                        "backup_id": row.id,
                        "error_code": row.error_code,
                    },
                )
            )
        db.commit()
        return backup_view(row)

    @router.post("")
    def request_backup(data: BackupRequest, db: Database, actor: Administrator) -> dict[str, Any]:
        # A dedicated connection retains the advisory lock across job/audit commits.
        # This also serializes the same request across backend processes.
        with engine.connect() as guard:
            acquired = guard.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name})
            if acquired != 1:
                raise HTTPException(409, detail={"code": "backup_busy"})
            try:
                return perform(data, db, actor)
            finally:
                guard.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})

    return router
