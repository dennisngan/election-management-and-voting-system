"""Retain special-paper observations and immutable accounting bases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0017_special_paper_snapshots"
down_revision: str | None = "0016_counter_stock_returns"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "special_paper_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_special_paper_snapshots_station_id", "special_paper_snapshots", ["station_id"]
    )
    op.create_table(
        "special_paper_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("special_paper_snapshots.id"),
                  nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("stock_snapshot_id", sa.Integer(), sa.ForeignKey("stock_snapshots.id"),
                  nullable=False),
        sa.Column("stock_snapshot_revision", sa.Integer(), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "revision", name="uq_special_paper_revision"),
        sa.UniqueConstraint("request_id", name="uq_special_paper_request"),
        sa.CheckConstraint("revision >= 1", name="ck_special_paper_revision"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    for column in ("snapshot_id", "stock_snapshot_id"):
        op.create_index("ix_special_paper_revisions_" + column,
                        "special_paper_revisions", [column])


def downgrade() -> None:
    op.drop_table("special_paper_revisions")
    op.drop_table("special_paper_snapshots")
