"""Append-only instructions linking a reviewed source count to its replacement round."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class LocalRecountInstruction(Base):
    __tablename__ = "local_recount_instructions"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_local_recount_request"),
        UniqueConstraint("new_round_id", name="uq_local_recount_new_round"),
        CheckConstraint("char_length(trim(reason)) > 0", name="ck_local_recount_reason"),
        CheckConstraint("event_at <= entered_at", name="ck_local_recount_time"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36))
    scope_id: Mapped[int] = mapped_column(ForeignKey("counting_scopes.id"), index=True)
    scope_revision_id: Mapped[int] = mapped_column(ForeignKey("counting_scope_revisions.id"))
    source_round_revision_id: Mapped[int] = mapped_column(ForeignKey("count_round_revisions.id"))
    new_round_id: Mapped[int] = mapped_column(ForeignKey("count_rounds.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str] = mapped_column(String(2000))
    event_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
