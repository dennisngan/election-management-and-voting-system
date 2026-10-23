"""Counter-to-PRO unissued-stock returns with immutable allocation lineage."""

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


class CounterStockReturn(Base):
    __tablename__ = "counter_stock_returns"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("polling_stations.id", name="fk_counter_stock_returns_station_id"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class CounterStockReturnRevision(Base):
    __tablename__ = "counter_stock_return_revisions"
    __table_args__ = (
        UniqueConstraint("return_id", "revision", name="uq_counter_stock_return_revision"),
        UniqueConstraint("request_id", name="uq_counter_stock_return_revisions_request_id"),
        CheckConstraint("revision >= 1", name="ck_counter_stock_return_revision"),
        CheckConstraint(
            "serial_from_value >= 0 AND serial_to_value >= serial_from_value AND "
            "quantity = serial_to_value - serial_from_value + 1",
            name="ck_counter_stock_return_quantity",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("counter_stock_returns.id", name="fk_counter_stock_return_revisions_return_id"),
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    payload_digest: Mapped[str] = mapped_column(String(64))
    counter_id: Mapped[int] = mapped_column(
        ForeignKey("issuance_counters.id", name="fk_counter_stock_return_revisions_counter_id"),
        index=True,
    )
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
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_counter_stock_return_revisions_actor_id")
    )
    reason: Mapped[str] = mapped_column(String(1000))
    allocation_basis: Mapped[list[dict[str, int | str]]] = mapped_column(JSON)
