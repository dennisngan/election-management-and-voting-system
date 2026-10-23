"""Retain remaining-stock snapshots and their frozen accounting basis."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0015_stock_snapshots"
down_revision: str | None = "0014_counter_allocations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "stock_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "station_id",
            sa.Integer(),
            sa.ForeignKey("polling_stations.id", name="fk_stock_snapshots_station_id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_stock_snapshots_station_id", "stock_snapshots", ["station_id"])
    op.create_table(
        "stock_snapshot_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("stock_snapshots.id", name="fk_stock_snapshot_revisions_snapshot_id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", name="fk_stock_snapshot_revisions_actor_id"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "revision", name="uq_stock_snapshot_revision"),
        sa.UniqueConstraint("request_id", name="uq_stock_snapshot_revisions_request_id"),
        sa.CheckConstraint("revision >= 1", name="ck_stock_snapshot_revision"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_stock_snapshot_revisions_snapshot_id", "stock_snapshot_revisions", ["snapshot_id"]
    )


def downgrade() -> None:
    op.drop_table("stock_snapshot_revisions")
    op.drop_table("stock_snapshots")
