"""Draft election configuration, with candidate ownership scoped to a constituency."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class Election(Base):
    __tablename__ = "elections"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    creation_digest: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class Constituency(Base):
    __tablename__ = "constituencies"
    __table_args__ = (
        UniqueConstraint("election_id", "code", name="uq_constituencies_election_code"),
        CheckConstraint("seats = 1", name="ck_constituencies_one_seat"),
        CheckConstraint("choices_per_ballot = 1", name="ck_constituencies_one_choice"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    creation_digest: Mapped[str] = mapped_column(String(64))
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"), index=True)
    code: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"))
    name: Mapped[str] = mapped_column(String(160))
    seats: Mapped[int] = mapped_column(Integer)
    choices_per_ballot: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint(
            "constituency_id", "ballot_number", name="uq_candidates_constituency_ballot_number"
        ),
        CheckConstraint("ballot_number > 0", name="ck_candidates_positive_ballot_number"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    creation_digest: Mapped[str] = mapped_column(String(64))
    constituency_id: Mapped[int] = mapped_column(ForeignKey("constituencies.id"), index=True)
    ballot_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(160))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
