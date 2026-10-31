"""Preserve atomic constituency recount instructions and their fixed membership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0034_constituency_recounts"
down_revision = "0033_local_recount_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "constituency_recount_instructions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column(
            "constituency_id", sa.Integer(), sa.ForeignKey("constituencies.id"), nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("basis_digest", sa.String(64), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("data", mysql.JSON(), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_constituency_recount_request"),
        sa.CheckConstraint("char_length(trim(reason)) > 0", name="ck_constituency_recount_reason"),
        sa.CheckConstraint("event_at <= entered_at", name="ck_constituency_recount_time"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_constituency_recount_instructions_constituency_id",
        "constituency_recount_instructions", ["constituency_id"],
    )
    op.create_table(
        "constituency_recount_members",
        sa.Column(
            "instruction_id", sa.Integer(),
            sa.ForeignKey("constituency_recount_instructions.id"), primary_key=True,
        ),
        sa.Column("scope_id", sa.Integer(), sa.ForeignKey("counting_scopes.id"), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column(
            "local_instruction_id", sa.Integer(),
            sa.ForeignKey("local_recount_instructions.id"), nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("local_instruction_id", name="uq_constituency_recount_local"),
        sa.UniqueConstraint("instruction_id", "position", name="uq_constituency_recount_position"),
        sa.CheckConstraint("position >= 0", name="ck_constituency_recount_position"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("constituency_recount_members")
    op.drop_table("constituency_recount_instructions")
