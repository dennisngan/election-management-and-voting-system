"""Frozen ballot-box identities and immutable handover/milestone revisions."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class BallotBox(Base):
    __tablename__ = "ballot_boxes"
    __table_args__ = (
        UniqueConstraint("origin_station_id", "box_reference", name="uq_box_origin_reference"),
        CheckConstraint(
            "(mode = 'local' AND origin_station_id = destination_station_id) OR "
            "(mode = 'send' AND origin_station_id <> destination_station_id)",
            name="ck_box_mode_destination",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin_station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    destination_station_id: Mapped[int] = mapped_column(
        ForeignKey("polling_stations.id"), index=True
    )
    mode: Mapped[str] = mapped_column(String(8))
    box_reference: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"))
    seal_reference: Mapped[str] = mapped_column(String(128))
    prepared_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))


class BoxEvent(Base):
    __tablename__ = "box_events"
    __table_args__ = (
        UniqueConstraint("box_id", "revision", name="uq_box_event_revision"),
        CheckConstraint("revision >= 1", name="ck_box_event_revision"),
        CheckConstraint(
            "kind IN ('prepared', 'departure', 'receipt', 'departure_correction', "
            "'receipt_correction')",
            name="ck_box_event_kind",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    box_id: Mapped[int] = mapped_column(ForeignKey("ballot_boxes.id"))
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(1000))


class BoxMilestone(Base):
    __tablename__ = "box_milestones"
    __table_args__ = (
        UniqueConstraint("station_id", "kind", "revision", name="uq_box_milestone_revision"),
        CheckConstraint("revision >= 1", name="ck_box_milestone_revision"),
        CheckConstraint(
            "kind IN ('conversion_complete', 'first_box_opening', "
            "'questionable_determination_start')",
            name="ck_box_milestone_kind",
        ),
        CheckConstraint(
            "(kind = 'first_box_opening' AND box_id IS NOT NULL) OR "
            "(kind <> 'first_box_opening' AND box_id IS NULL)",
            name="ck_box_milestone_box",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    kind: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer)
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    box_id: Mapped[int | None] = mapped_column(ForeignKey("ballot_boxes.id"))


class BoxRequest(Base):
    __tablename__ = "box_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    action: Mapped[str] = mapped_column(String(64))
    payload_digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
