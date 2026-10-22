"""Polling station arrangements and their ballot issuance counters."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class PollingStation(Base):
    __tablename__ = "polling_stations"
    __table_args__ = (
        UniqueConstraint("constituency_id", "code", name="uq_polling_stations_constituency_code"),
        # MySQL CHECK cannot use the auto-increment id; the API rejects self destinations
        # while holding the election lock.
        CheckConstraint(
            "(counting_mode = 'local' AND destination_station_id IS NULL) OR "
            "(counting_mode = 'send' AND destination_station_id IS NOT NULL)",
            name="ck_polling_stations_counting_arrangement",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    constituency_id: Mapped[int] = mapped_column(ForeignKey("constituencies.id"), index=True)
    code: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"))
    name: Mapped[str] = mapped_column(String(160))
    counting_mode: Mapped[str] = mapped_column(String(16))
    destination_station_id: Mapped[int | None] = mapped_column(
        ForeignKey("polling_stations.id"), nullable=True, index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    creation_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class IssuanceCounter(Base):
    __tablename__ = "issuance_counters"
    __table_args__ = (
        UniqueConstraint("station_id", "code", name="uq_issuance_counters_station_code"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    code: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"))
    name: Mapped[str] = mapped_column(String(160))
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    creation_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
