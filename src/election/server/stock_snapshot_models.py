"""Station remaining-stock snapshot heads and immutable frozen revisions."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from election.server.db import Base


def _quantity_json(value: Any, *, encode: bool, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: _quantity_json(item, encode=encode, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [_quantity_json(item, encode=encode) for item in value]
    if key == "quantity" or key.endswith("_quantity"):
        if encode and type(value) is int:
            return str(value)
        if (
            not encode
            and isinstance(value, str)
            and value.isascii()
            and value.removeprefix("-").isdecimal()
        ):
            return int(value)
    # Legacy numeric integers stay exact. A previously rounded float cannot be
    # reconstructed, so never turn it into an invented integer.
    return value


class SnapshotQuantityJSON(TypeDecorator[dict[str, Any]]):
    """Store exact quantities as decimal strings without changing public DTO types."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return _quantity_json(value, encode=True)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        return _quantity_json(value, encode=False)


class StockSnapshot(Base):
    __tablename__ = "stock_snapshots"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("polling_stations.id", name="fk_stock_snapshots_station_id"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class StockSnapshotRevision(Base):
    __tablename__ = "stock_snapshot_revisions"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "revision", name="uq_stock_snapshot_revision"),
        UniqueConstraint("request_id", name="uq_stock_snapshot_revisions_request_id"),
        CheckConstraint("revision >= 1", name="ck_stock_snapshot_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("stock_snapshots.id", name="fk_stock_snapshot_revisions_snapshot_id"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    payload_digest: Mapped[str] = mapped_column(String(64))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_stock_snapshot_revisions_actor_id")
    )
    reason: Mapped[str] = mapped_column(String(1000))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
