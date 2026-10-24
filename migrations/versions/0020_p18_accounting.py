"""Retain source-station P(18) accounting and exact command outcomes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0020_p18_accounting"
down_revision: str | None = "0019_turnout_source_basis"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "accounting_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("event_at", DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False),
        sa.Column("amendment_reason", sa.String(2000), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("submitted_at", DATETIME(fsp=6)),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.Column("approved_at", DATETIME(fsp=6)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.UniqueConstraint("station_id", "revision", name="uq_accounting_station_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_accounting_revision"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved')", name="ck_accounting_status"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_accounting_records_station_id", "accounting_records", ["station_id"])
    op.create_table(
        "accounting_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("accounting_requests")
    op.drop_table("accounting_records")
