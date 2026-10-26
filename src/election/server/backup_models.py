"""Observable backup requests retain successes and failures independently."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class ServerBackup(Base):
    __tablename__ = "server_backups"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="ck_backup_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(16))
    requested_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    cutoff_start: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    cutoff_end: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(80))
    manifest_data: Mapped[dict[str, Any]] = mapped_column(JSON)
