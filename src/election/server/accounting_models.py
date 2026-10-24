"""P(18) content revisions and replay receipts retain their exact frozen sources."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class AccountingRecord(Base):
    __tablename__ = "accounting_records"
    __table_args__ = (
        UniqueConstraint("station_id", "revision", name="uq_accounting_station_revision"),
        CheckConstraint("revision >= 1", name="ck_accounting_revision"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved')", name="ck_accounting_status"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
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
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class AccountingRequest(Base):
    __tablename__ = "accounting_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
