"""Scope identities, immutable source revisions and exclusive current box membership."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class CountingScope(Base):
    __tablename__ = "counting_scopes"
    __table_args__ = (
        UniqueConstraint("station_id", "reference", name="uq_scope_station_reference"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    reference: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))


class CountingScopeRevision(Base):
    __tablename__ = "counting_scope_revisions"
    __table_args__ = (
        UniqueConstraint("scope_id", "revision", name="uq_scope_revision"),
        CheckConstraint("revision >= 1", name="ck_scope_revision"),
        CheckConstraint("status IN ('draft', 'submitted')", name="ck_scope_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope_id: Mapped[int] = mapped_column(ForeignKey("counting_scopes.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    notes: Mapped[str] = mapped_column(String(2000))
    amendment_reason: Mapped[str] = mapped_column(String(2000))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class CountingScopeBox(Base):
    __tablename__ = "counting_scope_boxes"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    # Physical identity, rather than a source-scoped human reference, excludes
    # duplicate contribution even if callers race or use different scope names.
    box_id: Mapped[int] = mapped_column(ForeignKey("ballot_boxes.id"), primary_key=True)
    scope_id: Mapped[int] = mapped_column(ForeignKey("counting_scopes.id"), index=True)


class CountingScopeRequest(Base):
    __tablename__ = "counting_scope_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
