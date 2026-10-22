"""Explicit station assignments for individual staff accounts."""

from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class StationAssignment(Base):
    __tablename__ = "station_assignments"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    station_id: Mapped[int] = mapped_column(
        ForeignKey("polling_stations.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
