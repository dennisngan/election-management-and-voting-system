"""Retain counter allocation ownership and its original received-stock basis."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0014_counter_allocations"
down_revision: str | None = "0013_complaint_period_reports"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "stock_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_stock_allocations_station_id", "stock_allocations", ["station_id"])
    op.create_table(
        "stock_allocation_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "allocation_id", sa.Integer(), sa.ForeignKey("stock_allocations.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column(
            "counter_id", sa.Integer(), sa.ForeignKey("issuance_counters.id"), nullable=False
        ),
        sa.Column("counter_code", sa.String(32), nullable=False),
        sa.Column("counter_name", sa.String(160), nullable=False),
        sa.Column("series", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("serial_from", sa.String(18), nullable=False),
        sa.Column("serial_to", sa.String(18), nullable=False),
        sa.Column("serial_from_value", sa.BigInteger(), nullable=False),
        sa.Column("serial_to_value", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("receipt_basis", sa.JSON(), nullable=False),
        sa.UniqueConstraint("allocation_id", "revision", name="uq_stock_allocation_revision"),
        sa.UniqueConstraint("request_id", name="uq_stock_allocation_revisions_request_id"),
        sa.CheckConstraint("revision >= 1", name="ck_stock_allocation_revision"),
        sa.CheckConstraint(
            "serial_from_value >= 0 AND serial_to_value >= serial_from_value AND "
            "quantity = serial_to_value - serial_from_value + 1",
            name="ck_stock_allocation_quantity",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    for column in ("allocation_id", "counter_id", "series"):
        op.create_index(
            "ix_stock_allocation_revisions_" + column, "stock_allocation_revisions", [column]
        )


def downgrade() -> None:
    op.drop_table("stock_allocation_revisions")
    op.drop_table("stock_allocations")
