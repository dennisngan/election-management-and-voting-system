"""Normal turnout content revisions and replay-safe reporting commands."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class TurnoutRecord(Base):
    __tablename__ = "turnout_records"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "period_index", "revision", name="uq_turnout_period_revision"
        ),
        CheckConstraint("period_index >= 1 AND revision >= 1", name="ck_turnout_positive_revision"),
        CheckConstraint("status IN ('draft', 'submitted', 'approved')", name="ck_turnout_status"),
        CheckConstraint(
            "(supplied_hourly IS NULL OR supplied_hourly >= 0) AND "
            "(supplied_cumulative IS NULL OR supplied_cumulative >= 0)",
            name="ck_turnout_supplied_nonnegative",
        ),
        CheckConstraint(
            "(derived_hourly IS NULL OR derived_hourly >= 0) AND "
            "(derived_cumulative_start IS NULL OR derived_cumulative_start >= 0) AND "
            "(derived_cumulative_end IS NULL OR derived_cumulative_end >= 0)",
            name="ck_turnout_derived_nonnegative",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    period_index: Mapped[int] = mapped_column(BigInteger)
    revision: Mapped[int] = mapped_column(Integer)
    schedule_revision: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    end_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    supplied_hourly: Mapped[int | None] = mapped_column(BigInteger)
    supplied_cumulative: Mapped[int | None] = mapped_column(BigInteger)
    provenance: Mapped[str] = mapped_column(
        String(32), default="external_manual", server_default="external_manual",
    )
    source_basis: Mapped[dict[str, Any] | None] = mapped_column(SnapshotQuantityJSON)
    source_context: Mapped[str] = mapped_column(String(2000))
    event_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(16))
    amendment_reason: Mapped[str] = mapped_column(String(2000))
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    derived_hourly: Mapped[int | None] = mapped_column(BigInteger)
    derived_cumulative_start: Mapped[int | None] = mapped_column(BigInteger)
    derived_cumulative_end: Mapped[int | None] = mapped_column(BigInteger)
    basis_predecessor_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("turnout_records.id")
    )
    basis_predecessor_revision: Mapped[int | None] = mapped_column(Integer)


class TurnoutRequest(Base):
    __tablename__ = "turnout_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
