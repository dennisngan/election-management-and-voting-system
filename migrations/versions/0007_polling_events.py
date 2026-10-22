"""Preserve polling-event revisions, approvals and command outcomes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007_polling_events"
down_revision: str | None = "0006_election_lifecycle"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "polling_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("estimated_clear_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("amendment_reason", sa.String(2000), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("approved_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        sa.Column("planned_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("station_id", "kind", "revision", name="uq_polling_record_revision"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_polling_records_station_id", "polling_records", ["station_id"])
    op.create_table(
        "polling_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("polling_requests")
    op.drop_index("ix_polling_records_station_id", table_name="polling_records")
    op.drop_table("polling_records")
