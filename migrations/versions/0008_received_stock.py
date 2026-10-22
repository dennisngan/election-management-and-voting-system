"""Preserve received-stock pool ranges and immutable correction revisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0008_received_stock"
down_revision: str | None = "0007_polling_events"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "stock_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_stock_receipts_station_id", "stock_receipts", ["station_id"])
    op.create_table(
        "stock_receipt_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("receipt_id", sa.Integer(), sa.ForeignKey("stock_receipts.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("series", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("ordinary_quantity", sa.BigInteger(), nullable=False),
        sa.Column("replacement_quantity", sa.BigInteger(), nullable=False),
        sa.Column("tendered_quantity", sa.BigInteger(), nullable=False),
        sa.Column("total_quantity", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("receipt_id", "revision", name="uq_stock_receipt_revision"),
        sa.UniqueConstraint("request_id", name="uq_stock_receipt_revisions_request_id"),
        sa.CheckConstraint(
            "ordinary_quantity >= 0 AND replacement_quantity >= 0 AND tendered_quantity >= 0",
            name="ck_stock_receipt_nonnegative_pools",
        ),
        sa.CheckConstraint(
            "total_quantity > 0 AND total_quantity = ordinary_quantity + "
            "replacement_quantity + tendered_quantity",
            name="ck_stock_receipt_balanced_total",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_stock_receipt_revisions_receipt_id", "stock_receipt_revisions", ["receipt_id"]
    )
    op.create_index("ix_stock_receipt_revisions_series", "stock_receipt_revisions", ["series"])
    op.create_table(
        "stock_receipt_ranges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "revision_id", sa.Integer(), sa.ForeignKey("stock_receipt_revisions.id"), nullable=False
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("pool", sa.String(16), nullable=False),
        sa.Column("serial_from", sa.String(18), nullable=False),
        sa.Column("serial_to", sa.String(18), nullable=False),
        sa.Column("serial_from_value", sa.BigInteger(), nullable=False),
        sa.Column("serial_to_value", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("revision_id", "line_number", name="uq_stock_receipt_range_line"),
        sa.CheckConstraint(
            "pool IN ('ordinary', 'replacement', 'tendered')", name="ck_stock_receipt_range_pool"
        ),
        sa.CheckConstraint(
            "serial_from_value >= 0 AND serial_to_value >= serial_from_value AND "
            "quantity = serial_to_value - serial_from_value + 1",
            name="ck_stock_receipt_range_quantity",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_stock_receipt_ranges_revision_id", "stock_receipt_ranges", ["revision_id"])


def downgrade() -> None:
    op.drop_table("stock_receipt_ranges")
    op.drop_table("stock_receipt_revisions")
    op.drop_table("stock_receipts")
