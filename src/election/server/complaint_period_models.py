"""Frozen P19 received-cohort revisions and exact immutable case membership."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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


class ComplaintPeriodRecord(Base):
    __tablename__ = "complaint_period_records"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "period_index", "revision", name="uq_complaint_period_revision"
        ),
        CheckConstraint("period_index >= 1 AND revision >= 1", name="ck_complaint_period_revision"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved')", name="ck_complaint_period_status"
        ),
        CheckConstraint(
            "total_received >= 0 AND total_completed >= 0 AND total_in_progress >= 0 "
            "AND total_received = total_completed + total_in_progress",
            name="ck_complaint_period_counts",
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
    status: Mapped[str] = mapped_column(String(16))
    basis_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    basis_hash: Mapped[str] = mapped_column(String(64))
    total_received: Mapped[int] = mapped_column(BigInteger)
    total_completed: Mapped[int] = mapped_column(BigInteger)
    total_in_progress: Mapped[int] = mapped_column(BigInteger)
    group_counts: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amendment_reason: Mapped[str] = mapped_column(String(1000))
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class ComplaintPeriodCase(Base):
    __tablename__ = "complaint_period_cases"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    record_id: Mapped[int] = mapped_column(
        ForeignKey("complaint_period_records.id"), primary_key=True
    )
    case_id: Mapped[int] = mapped_column(ForeignKey("complaint_cases.id"), primary_key=True)
    case_revision_id: Mapped[int] = mapped_column(ForeignKey("complaint_revisions.id"))
