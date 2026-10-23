"""Retain counter-to-PRO returns and their original allocation-source parts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0016_counter_stock_returns"
down_revision: str | None = "0015_stock_snapshots"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "counter_stock_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "station_id",
            sa.Integer(),
            sa.ForeignKey("polling_stations.id", name="fk_counter_stock_returns_station_id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_counter_stock_returns_station_id", "counter_stock_returns", ["station_id"]
    )
    op.create_table(
        "counter_stock_return_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "return_id",
            sa.Integer(),
            sa.ForeignKey(
                "counter_stock_returns.id", name="fk_counter_stock_return_revisions_return_id"
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column(
            "counter_id",
            sa.Integer(),
            sa.ForeignKey(
                "issuance_counters.id", name="fk_counter_stock_return_revisions_counter_id"
            ),
            nullable=False,
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
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", name="fk_counter_stock_return_revisions_actor_id"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("allocation_basis", sa.JSON(), nullable=False),
        sa.UniqueConstraint("return_id", "revision", name="uq_counter_stock_return_revision"),
        sa.UniqueConstraint("request_id", name="uq_counter_stock_return_revisions_request_id"),
        sa.CheckConstraint("revision >= 1", name="ck_counter_stock_return_revision"),
        sa.CheckConstraint(
            "serial_from_value >= 0 AND serial_to_value >= serial_from_value AND "
            "quantity = serial_to_value - serial_from_value + 1",
            name="ck_counter_stock_return_quantity",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    for column in ("return_id", "counter_id", "series"):
        op.create_index(
            "ix_counter_stock_return_revisions_" + column,
            "counter_stock_return_revisions",
            [column],
        )


def downgrade() -> None:
    op.drop_table("counter_stock_return_revisions")
    op.drop_table("counter_stock_returns")
