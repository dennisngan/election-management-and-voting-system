"""Election invalid-reason configuration with preserved source and label revisions."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class InvalidBallotReason(Base):
    __tablename__ = "invalid_ballot_reasons"
    __table_args__ = (
        UniqueConstraint("election_id", "code", name="uq_invalid_reason_code"),
        CheckConstraint("stage IN ('f1', 'f2')", name="ck_invalid_reason_stage"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"), index=True)
    code: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"))
    stage: Mapped[str] = mapped_column(String(8))
    verified_source: Mapped[bool] = mapped_column(Boolean)
    source_english: Mapped[str] = mapped_column(String(512))
    source_letter: Mapped[str | None] = mapped_column(String(8))
    reference_page: Mapped[int | None] = mapped_column(Integer)
    reference_printed_page: Mapped[int | None] = mapped_column(Integer)
    is_other: Mapped[bool] = mapped_column(Boolean)


class InvalidBallotReasonRevision(Base):
    __tablename__ = "invalid_ballot_reason_revisions"
    __table_args__ = (
        UniqueConstraint("reason_id", "revision", name="uq_invalid_reason_revision"),
        CheckConstraint("revision >= 1", name="ck_invalid_reason_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reason_id: Mapped[int] = mapped_column(ForeignKey("invalid_ballot_reasons.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    label_en: Mapped[str] = mapped_column(String(512))
    label_tc: Mapped[str] = mapped_column(String(512))
    label_sc: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean)
    explanation_required: Mapped[bool] = mapped_column(Boolean)
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class InvalidBallotReasonRequest(Base):
    __tablename__ = "invalid_ballot_reason_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
