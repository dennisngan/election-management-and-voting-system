"""Retain server backup request outcomes without exposing credentials."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0028_server_backups"
down_revision: str | None = "0025_count_round_selections"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "server_backups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", DATETIME(fsp=6), nullable=False),
        sa.Column("completed_at", DATETIME(fsp=6)),
        sa.Column("cutoff_start", DATETIME(fsp=6)),
        sa.Column("cutoff_end", DATETIME(fsp=6)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("manifest_data", sa.JSON(), nullable=False),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="ck_backup_status"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("server_backups")
