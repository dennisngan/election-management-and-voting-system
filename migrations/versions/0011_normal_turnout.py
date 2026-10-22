"""Preserve supplied normal turnout, reviewed cumulative bases and command receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0011_normal_turnout"
down_revision: str | None = "0010_box_handover"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "turnout_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("period_index", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column("start_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("end_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("supplied_hourly", sa.BigInteger()),
        sa.Column("supplied_cumulative", sa.BigInteger()),
        sa.Column("source_context", sa.String(2000), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6)),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amendment_reason", sa.String(2000), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6)),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.Column("approved_at", mysql.DATETIME(fsp=6)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.Column("derived_hourly", sa.BigInteger()),
        sa.Column("derived_cumulative_start", sa.BigInteger()),
        sa.Column("derived_cumulative_end", sa.BigInteger()),
        sa.Column("basis_predecessor_record_id", sa.Integer(), sa.ForeignKey("turnout_records.id")),
        sa.Column("basis_predecessor_revision", sa.Integer()),
        sa.UniqueConstraint(
            "station_id", "period_index", "revision", name="uq_turnout_period_revision"
        ),
        sa.CheckConstraint(
            "period_index >= 1 AND revision >= 1", name="ck_turnout_positive_revision"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved')", name="ck_turnout_status"
        ),
        sa.CheckConstraint(
            "(supplied_hourly IS NULL OR supplied_hourly >= 0) AND "
            "(supplied_cumulative IS NULL OR supplied_cumulative >= 0)",
            name="ck_turnout_supplied_nonnegative",
        ),
        sa.CheckConstraint(
            "(derived_hourly IS NULL OR derived_hourly >= 0) AND "
            "(derived_cumulative_start IS NULL OR derived_cumulative_start >= 0) AND "
            "(derived_cumulative_end IS NULL OR derived_cumulative_end >= 0)",
            name="ck_turnout_derived_nonnegative",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_turnout_records_station_id", "turnout_records", ["station_id"])
    op.create_table(
        "turnout_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("turnout_requests")
    op.drop_table("turnout_records")
