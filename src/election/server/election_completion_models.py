"""Append-only finalized outcomes, reopening events and original request receipts."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class ElectionCompletionEvent(Base):
    __tablename__ = "election_completion_events"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "election_revision", name="uq_election_completion_event_revision",
        ),
        CheckConstraint(
            "kind IN ('finalization', 'reopening')", name="ck_election_completion_event_kind",
        ),
        CheckConstraint("election_revision >= 1", name="ck_election_completion_event_revision"),
        CheckConstraint(
            "(kind = 'finalization' AND previous_finalization_id IS NULL) OR "
            "(kind = 'reopening' AND previous_finalization_id IS NOT NULL "
            "AND char_length(trim(reason)) > 0)",
            name="ck_election_completion_event_predecessor",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    election_id: Mapped[int] = mapped_column(
        ForeignKey("elections.id", ondelete="RESTRICT"), index=True,
    )
    kind: Mapped[str] = mapped_column(String(16))
    election_revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    accepted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    reason: Mapped[str] = mapped_column(String(2000))
    previous_finalization_id: Mapped[int | None] = mapped_column(
        ForeignKey("election_completion_events.id", ondelete="RESTRICT"), nullable=True,
    )
    basis_digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class ElectionCompletionRequest(Base):
    __tablename__ = "election_completion_requests"
    __table_args__ = (
        CheckConstraint(
            "action IN ('finalization', 'reopening')", name="ck_election_completion_request_action",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    election_id: Mapped[int] = mapped_column(
        ForeignKey("elections.id", ondelete="RESTRICT"), index=True,
    )
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    event_id: Mapped[int] = mapped_column(
        ForeignKey("election_completion_events.id", ondelete="RESTRICT"),
    )
    action: Mapped[str] = mapped_column(String(16))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
    accepted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
