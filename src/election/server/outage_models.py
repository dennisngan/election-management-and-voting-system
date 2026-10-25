"""Preserved application outages, paper identities and atomic reentry receipts."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from election.server.db import Base
from election.server.stock_snapshot_models import SnapshotQuantityJSON


class ApplicationOutage(Base):
    __tablename__ = "application_outages"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)


class ApplicationOutageRevision(Base):
    __tablename__ = "application_outage_revisions"
    __table_args__ = (
        UniqueConstraint("outage_id", "revision", name="uq_outage_revision"),
        CheckConstraint("revision >= 1", name="ck_outage_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outage_id: Mapped[int] = mapped_column(ForeignKey("application_outages.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    amendment_reason: Mapped[str] = mapped_column(String(2000))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class OutagePaperRecord(Base):
    __tablename__ = "outage_paper_records"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "workflow", "paper_reference", name="uq_station_workflow_paper"
        ),
        CheckConstraint("workflow IN ('count', 'turnout', 'allocation')", name="ck_paper_workflow"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outage_id: Mapped[int] = mapped_column(ForeignKey("application_outages.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"), index=True)
    workflow: Mapped[str] = mapped_column(String(16))
    paper_reference: Mapped[str] = mapped_column(String(160, collation="utf8mb4_bin"))


class OutagePaperRevision(Base):
    __tablename__ = "outage_paper_revisions"
    __table_args__ = (
        UniqueConstraint("paper_id", "revision", name="uq_outage_paper_revision"),
        CheckConstraint("revision >= 1", name="ck_outage_paper_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("outage_paper_records.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    amendment_reason: Mapped[str] = mapped_column(String(2000))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class PaperReentry(Base):
    __tablename__ = "paper_reentries"
    __table_args__ = (
        UniqueConstraint("workflow", "request_id", name="uq_paper_workflow_request"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    paper_id: Mapped[int] = mapped_column(ForeignKey("outage_paper_records.id"), primary_key=True)
    paper_revision_id: Mapped[int] = mapped_column(ForeignKey("outage_paper_revisions.id"))
    workflow: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    entered_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    record: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class OutageReconciliation(Base):
    __tablename__ = "outage_reconciliations"
    __table_args__ = (
        UniqueConstraint("outage_id", "revision", name="uq_outage_reconciliation_revision"),
        CheckConstraint("revision >= 1", name="ck_outage_reconciliation_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outage_id: Mapped[int] = mapped_column(ForeignKey("application_outages.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    accepted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    reason: Mapped[str] = mapped_column(String(2000))
    basis_digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)


class OutageRequest(Base):
    __tablename__ = "outage_requests"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("polling_stations.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(SnapshotQuantityJSON)
