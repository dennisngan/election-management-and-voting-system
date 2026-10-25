"""Auditable physical-paper dispositions, separate from immutable tally observations."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class CountPhysicalDecision(Base):
    __tablename__ = "count_physical_decisions"
    __table_args__ = (
        UniqueConstraint(
            "round_id", "source", "revision", name="uq_count_physical_decision_revision"
        ),
        CheckConstraint("revision >= 1", name="ck_count_physical_decision_revision"),
        CheckConstraint("source IN ('stock', 'turnout')", name="ck_count_physical_decision_source"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("count_rounds.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    round_revision_id: Mapped[int] = mapped_column(
        ForeignKey("count_round_revisions.id"), index=True
    )
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    accepted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    reason: Mapped[str] = mapped_column(String(2000))
    fingerprint: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
