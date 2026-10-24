"""Retained EPR fallback content, confirmed source selection and command identities."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class FallbackRecord(Base):
    __tablename__ = "fallback_records"
    __table_args__ = (
        CheckConstraint("kind IN ('activation', 'recovery')", name="ck_fallback_kind"),
        CheckConstraint("revision >= 1", name="ck_fallback_head_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    activation_id: Mapped[int | None] = mapped_column(ForeignKey("fallback_records.id"))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class FallbackRevision(Base):
    __tablename__ = "fallback_revisions"
    __table_args__ = (
        UniqueConstraint("record_id", "revision", name="uq_fallback_revision"),
        CheckConstraint("revision >= 1", name="ck_fallback_revision"),
        CheckConstraint("status IN ('draft', 'submitted', 'approved')", name="ck_fallback_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("fallback_records.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    schedule_revision: Mapped[int] = mapped_column(Integer)
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(16))
    stock_snapshot_id: Mapped[int] = mapped_column(ForeignKey("stock_snapshots.id"))
    stock_snapshot_revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(2000))
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class FallbackRequest(Base):
    __tablename__ = "fallback_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
