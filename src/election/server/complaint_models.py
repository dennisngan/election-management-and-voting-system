"""Complaint category provenance, immutable case revisions and reserved references."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base


class ComplaintCategory(Base):
    __tablename__ = "complaint_categories"
    __table_args__ = (
        UniqueConstraint("election_id", "code", name="uq_complaint_category_code"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"))
    code: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"))
    verified_source: Mapped[bool] = mapped_column(Boolean)
    source_english: Mapped[str] = mapped_column(String(255))
    reference_page: Mapped[int | None] = mapped_column(Integer)
    is_other: Mapped[bool] = mapped_column(Boolean)


class ComplaintCategoryRevision(Base):
    __tablename__ = "complaint_category_revisions"
    __table_args__ = (
        UniqueConstraint("category_id", "revision", name="uq_complaint_category_revision"),
        CheckConstraint("revision >= 1", name="ck_complaint_category_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("complaint_categories.id"))
    revision: Mapped[int] = mapped_column(Integer)
    label_en: Mapped[str] = mapped_column(String(255))
    label_tc: Mapped[str] = mapped_column(String(255))
    label_sc: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean)
    description_required: Mapped[bool] = mapped_column(Boolean)
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class ComplaintCase(Base):
    __tablename__ = "complaint_cases"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    ever_submitted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class ComplaintRevision(Base):
    __tablename__ = "complaint_revisions"
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_complaint_case_revision"),
        CheckConstraint("revision >= 1", name="ck_complaint_case_revision"),
        CheckConstraint(
            "(work_status = 'in_progress' AND completed_at IS NULL) OR "
            "(work_status = 'completed' AND completed_at IS NOT NULL "
            "AND completed_at >= received_at)",
            name="ck_complaint_completion",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("complaint_cases.id"))
    revision: Mapped[int] = mapped_column(Integer)
    case_reference: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"))
    received_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    category_id: Mapped[int] = mapped_column(ForeignKey("complaint_categories.id"))
    category_revision_id: Mapped[int] = mapped_column(ForeignKey("complaint_category_revisions.id"))
    category_revision: Mapped[int] = mapped_column(Integer)
    category_code: Mapped[str] = mapped_column(String(64))
    category_label_en: Mapped[str] = mapped_column(String(255))
    category_label_tc: Mapped[str] = mapped_column(String(255))
    category_label_sc: Mapped[str] = mapped_column(String(255))
    category_verified_source: Mapped[bool] = mapped_column(Boolean)
    category_source_english: Mapped[str] = mapped_column(String(255))
    category_reference_page: Mapped[int | None] = mapped_column(Integer)
    is_other: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(Text)
    work_status: Mapped[str] = mapped_column(String(16))
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amendment_reason: Mapped[str] = mapped_column(String(1000))


class ComplaintReference(Base):
    __tablename__ = "complaint_references"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), primary_key=True)
    reference: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("complaint_cases.id"))


class ComplaintRequest(Base):
    __tablename__ = "complaint_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"))
    station_id: Mapped[int | None] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    action: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
