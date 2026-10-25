"""Preserved count-round identities and immutable F1 draft observations."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class CountRound(Base):
    __tablename__ = "count_rounds"
    __table_args__ = (
        UniqueConstraint("scope_id", "round_number", name="uq_count_scope_round"),
        CheckConstraint("round_number >= 1", name="ck_count_round_number"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope_id: Mapped[int] = mapped_column(ForeignKey("counting_scopes.id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)


class CountRoundRevision(Base):
    __tablename__ = "count_round_revisions"
    __table_args__ = (
        UniqueConstraint("round_id", "revision", name="uq_count_round_revision"),
        CheckConstraint("revision >= 1", name="ck_count_round_revision"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved')", name="ck_count_round_status"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("count_rounds.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    notes: Mapped[str] = mapped_column(String(2000))
    amendment_reason: Mapped[str] = mapped_column(String(2000))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class CountRoundRequest(Base):
    __tablename__ = "count_round_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
