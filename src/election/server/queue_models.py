"""Immutable queue observations and explicit unchanged confirmations."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class QueueEvent(Base):
    __tablename__ = "queue_events"
    __table_args__ = (
        UniqueConstraint("station_id", "revision", name="uq_queue_station_revision"),
        CheckConstraint("revision >= 1", name="ck_queue_positive_revision"),
        CheckConstraint("band IN ('under_30', '30_59', '60_90', 'over_90')", name="ck_queue_band"),
        CheckConstraint(
            "(kind = 'observation' AND confirmed_event_id IS NULL) OR "
            "(kind = 'unchanged_confirmation' AND confirmed_event_id IS NOT NULL)",
            name="ck_queue_event_kind",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    band: Mapped[str] = mapped_column(String(16))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    confirmed_event_id: Mapped[int | None] = mapped_column(ForeignKey("queue_events.id"))
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(1000))
