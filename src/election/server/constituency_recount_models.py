"""Preserved constituency instructions and their original required local recounts."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class ConstituencyRecountInstruction(Base):
    __tablename__ = "constituency_recount_instructions"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_constituency_recount_request"),
        CheckConstraint("char_length(trim(reason)) > 0", name="ck_constituency_recount_reason"),
        CheckConstraint("event_at <= entered_at", name="ck_constituency_recount_time"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36))
    constituency_id: Mapped[int] = mapped_column(ForeignKey("constituencies.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(2000))
    basis_digest: Mapped[str] = mapped_column(String(64))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class ConstituencyRecountMember(Base):
    __tablename__ = "constituency_recount_members"
    __table_args__ = (
        UniqueConstraint("local_instruction_id", name="uq_constituency_recount_local"),
        UniqueConstraint("instruction_id", "position", name="uq_constituency_recount_position"),
        CheckConstraint("position >= 0", name="ck_constituency_recount_position"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    instruction_id: Mapped[int] = mapped_column(
        ForeignKey("constituency_recount_instructions.id"), primary_key=True,
    )
    scope_id: Mapped[int] = mapped_column(ForeignKey("counting_scopes.id"), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    local_instruction_id: Mapped[int] = mapped_column(ForeignKey("local_recount_instructions.id"))
    position: Mapped[int] = mapped_column(Integer)
