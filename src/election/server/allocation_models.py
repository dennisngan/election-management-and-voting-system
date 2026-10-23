"""Counter-owned ordinary intervals and immutable allocation revisions."""

from datetime import datetime

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


class StockAllocation(Base):
    __tablename__ = "stock_allocations"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class StockAllocationRevision(Base):
    __tablename__ = "stock_allocation_revisions"
    __table_args__ = (
        UniqueConstraint("allocation_id", "revision", name="uq_stock_allocation_revision"),
        CheckConstraint("revision >= 1", name="ck_stock_allocation_revision"),
        CheckConstraint(
            "serial_from_value >= 0 AND serial_to_value >= serial_from_value AND "
            "quantity = serial_to_value - serial_from_value + 1",
            name="ck_stock_allocation_quantity",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("stock_allocations.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    counter_id: Mapped[int] = mapped_column(ForeignKey("issuance_counters.id"), index=True)
    counter_code: Mapped[str] = mapped_column(String(32))
    counter_name: Mapped[str] = mapped_column(String(160))
    series: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), index=True)
    serial_from: Mapped[str] = mapped_column(String(18))
    serial_to: Mapped[str] = mapped_column(String(18))
    serial_from_value: Mapped[int] = mapped_column(BigInteger)
    serial_to_value: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(BigInteger)
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    receipt_basis: Mapped[list[dict[str, int]]] = mapped_column(JSON)
