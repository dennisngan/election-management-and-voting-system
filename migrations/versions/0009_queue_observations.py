"""Preserve queue observation and unchanged-confirmation events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0009_queue_observations"
down_revision: str | None = "0008_received_stock"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "queue_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("band", sa.String(16), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("confirmed_event_id", sa.Integer(), sa.ForeignKey("queue_events.id")),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.UniqueConstraint("station_id", "revision", name="uq_queue_station_revision"),
        sa.UniqueConstraint("request_id", name="uq_queue_events_request_id"),
        sa.CheckConstraint("revision >= 1", name="ck_queue_positive_revision"),
        sa.CheckConstraint(
            "band IN ('under_30', '30_59', '60_90', 'over_90')", name="ck_queue_band"
        ),
        sa.CheckConstraint(
            "(kind = 'observation' AND confirmed_event_id IS NULL) OR "
            "(kind = 'unchanged_confirmation' AND confirmed_event_id IS NOT NULL)",
            name="ck_queue_event_kind",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_queue_events_station_id", "queue_events", ["station_id"])


def downgrade() -> None:
    op.drop_table("queue_events")
