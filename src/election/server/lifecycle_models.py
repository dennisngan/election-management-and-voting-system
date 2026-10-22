"""Election schedule and the single operational-election pointer."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class ElectionSchedule(Base):
    __tablename__ = "election_schedules"
    __table_args__ = (
        CheckConstraint(
            "reporting_interval_minutes BETWEEN 1 AND 1440",
            name="ck_election_schedules_reporting_interval",
        ),
        CheckConstraint(
            "planned_closing_at > planned_opening_at", name="ck_election_schedules_ordered_times"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"), primary_key=True)
    election_date: Mapped[date] = mapped_column(Date)
    planned_opening_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    planned_closing_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    reporting_interval_minutes: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class ActiveElection(Base):
    __tablename__ = "active_election"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_active_election_singleton"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    election_id: Mapped[int | None] = mapped_column(ForeignKey("elections.id"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
