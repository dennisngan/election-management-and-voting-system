"""Preserved Supervisor tie resolutions and immutable request outcomes."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class ConstituencyTieResolution(Base):
    __tablename__ = "constituency_tie_resolutions"
    __table_args__ = (
        UniqueConstraint("constituency_id", "revision", name="uq_constituency_tie_revision"),
        CheckConstraint("revision >= 1", name="ck_constituency_tie_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    constituency_id: Mapped[int] = mapped_column(ForeignKey("constituencies.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    accepted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    reason: Mapped[str] = mapped_column(String(2000))
    basis_digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class ConstituencyResultRequest(Base):
    __tablename__ = "constituency_result_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    constituency_id: Mapped[int] = mapped_column(ForeignKey("constituencies.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
