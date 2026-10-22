"""Revision-bound polling events and duplicate-safe command receipts."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class PollingRecord(Base):
    __tablename__ = "polling_records"
    __table_args__ = (
        UniqueConstraint("station_id", "kind", "revision", name="uq_polling_record_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    event_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    estimated_clear_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    reason: Mapped[str] = mapped_column(String(2000))
    amendment_reason: Mapped[str] = mapped_column(String(2000))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    schedule_revision: Mapped[int] = mapped_column(Integer)
    planned_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class PollingRequest(Base):
    __tablename__ = "polling_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
