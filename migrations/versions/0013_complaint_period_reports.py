"""Preserve P19 report bases, received-cohort counts and case membership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0013_complaint_period_reports"
down_revision: str | None = "0012_complaint_catalog_cases"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "complaint_period_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("period_index", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column("start_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("end_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("basis_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("basis_hash", sa.String(64), nullable=False),
        sa.Column("total_received", sa.BigInteger(), nullable=False),
        sa.Column("total_completed", sa.BigInteger(), nullable=False),
        sa.Column("total_in_progress", sa.BigInteger(), nullable=False),
        sa.Column("group_counts", sa.JSON(), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amendment_reason", sa.String(1000), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6)),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.Column("approved_at", mysql.DATETIME(fsp=6)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.UniqueConstraint(
            "station_id", "period_index", "revision", name="uq_complaint_period_revision"
        ),
        sa.CheckConstraint(
            "period_index >= 1 AND revision >= 1", name="ck_complaint_period_revision"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved')", name="ck_complaint_period_status"
        ),
        sa.CheckConstraint(
            "total_received >= 0 AND total_completed >= 0 AND total_in_progress >= 0 "
            "AND total_received = total_completed + total_in_progress",
            name="ck_complaint_period_counts",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_complaint_period_records_station_id", "complaint_period_records", ["station_id"]
    )
    op.create_table(
        "complaint_period_cases",
        sa.Column(
            "record_id",
            sa.Integer(),
            sa.ForeignKey("complaint_period_records.id"),
            primary_key=True,
        ),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("complaint_cases.id"), primary_key=True),
        sa.Column(
            "case_revision_id",
            sa.Integer(),
            sa.ForeignKey("complaint_revisions.id"),
            nullable=False,
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("complaint_period_cases")
    op.drop_index("ix_complaint_period_records_station_id", table_name="complaint_period_records")
    op.drop_table("complaint_period_records")
