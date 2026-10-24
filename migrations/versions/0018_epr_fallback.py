"""Retain EPR fallback content revisions and confirmed source selection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0018_epr_fallback"
down_revision: str | None = "0017_special_paper_snapshots"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "fallback_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approved_revision", sa.Integer(), nullable=True),
        sa.Column("activation_id", sa.Integer(),
                  sa.ForeignKey("fallback_records.id"), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("kind IN ('activation', 'recovery')", name="ck_fallback_kind"),
        sa.CheckConstraint("revision >= 1", name="ck_fallback_head_revision"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_fallback_records_station_id", "fallback_records", ["station_id"])
    op.create_table(
        "fallback_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("fallback_records.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stock_snapshot_id", sa.Integer(),
                  sa.ForeignKey("stock_snapshots.id"), nullable=False),
        sa.Column("stock_snapshot_revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("approved_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("record_id", "revision", name="uq_fallback_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_fallback_revision"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved')",
                           name="ck_fallback_status"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_fallback_revisions_record_id", "fallback_revisions", ["record_id"])
    op.create_table(
        "fallback_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("fallback_requests")
    op.drop_table("fallback_revisions")
    op.drop_table("fallback_records")
