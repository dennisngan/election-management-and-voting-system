"""Special-paper observation heads and immutable accounting revisions."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class SpecialPaperSnapshot(Base):
    __tablename__ = "special_paper_snapshots"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class SpecialPaperRevision(Base):
    __tablename__ = "special_paper_revisions"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "revision", name="uq_special_paper_revision"),
        UniqueConstraint("request_id", name="uq_special_paper_request"),
        CheckConstraint("revision >= 1", name="ck_special_paper_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("special_paper_snapshots.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    payload_digest: Mapped[str] = mapped_column(String(64))
    stock_snapshot_id: Mapped[int] = mapped_column(ForeignKey("stock_snapshots.id"), index=True)
    stock_snapshot_revision: Mapped[int] = mapped_column(Integer)
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
