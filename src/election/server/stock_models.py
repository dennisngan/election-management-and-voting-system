"""Received-stock heads and immutable receipt/range revisions."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class StockReceipt(Base):
    __tablename__ = "stock_receipts"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class StockReceiptRevision(Base):
    __tablename__ = "stock_receipt_revisions"
    __table_args__ = (
        UniqueConstraint("receipt_id", "revision", name="uq_stock_receipt_revision"),
        CheckConstraint(
            "ordinary_quantity >= 0 AND replacement_quantity >= 0 AND tendered_quantity >= 0",
            name="ck_stock_receipt_nonnegative_pools",
        ),
        CheckConstraint(
            "total_quantity > 0 AND total_quantity = ordinary_quantity + "
            "replacement_quantity + tendered_quantity",
            name="ck_stock_receipt_balanced_total",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("stock_receipts.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    series: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), index=True)
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    ordinary_quantity: Mapped[int] = mapped_column(BigInteger)
    replacement_quantity: Mapped[int] = mapped_column(BigInteger)
    tendered_quantity: Mapped[int] = mapped_column(BigInteger)
    total_quantity: Mapped[int] = mapped_column(BigInteger)


class StockReceiptRange(Base):
    __tablename__ = "stock_receipt_ranges"
    __table_args__ = (
        UniqueConstraint("revision_id", "line_number", name="uq_stock_receipt_range_line"),
        CheckConstraint(
            "pool IN ('ordinary', 'replacement', 'tendered')", name="ck_stock_receipt_range_pool"
        ),
        CheckConstraint(
            "serial_from_value >= 0 AND serial_to_value >= serial_from_value AND "
            "quantity = serial_to_value - serial_from_value + 1",
            name="ck_stock_receipt_range_quantity",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("stock_receipt_revisions.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    pool: Mapped[str] = mapped_column(String(16))
    serial_from: Mapped[str] = mapped_column(String(18))
    serial_to: Mapped[str] = mapped_column(String(18))
    serial_from_value: Mapped[int] = mapped_column(BigInteger)
    serial_to_value: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(BigInteger)
