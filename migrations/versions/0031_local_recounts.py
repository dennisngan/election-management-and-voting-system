"""Preserve local recount instructions and their source/replacement identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0031_local_recounts"
down_revision = "0030_counting_results_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_recount_instructions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("scope_id", sa.Integer(), sa.ForeignKey("counting_scopes.id"), nullable=False),
        sa.Column(
            "scope_revision_id",
            sa.Integer(),
            sa.ForeignKey("counting_scope_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "source_round_revision_id",
            sa.Integer(),
            sa.ForeignKey("count_round_revisions.id"),
            nullable=False,
        ),
        sa.Column("new_round_id", sa.Integer(), sa.ForeignKey("count_rounds.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_local_recount_request"),
        sa.UniqueConstraint("new_round_id", name="uq_local_recount_new_round"),
        sa.CheckConstraint("char_length(trim(reason)) > 0", name="ck_local_recount_reason"),
        sa.CheckConstraint("event_at <= entered_at", name="ck_local_recount_time"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_local_recount_instructions_scope_id", "local_recount_instructions", ["scope_id"]
    )


def downgrade() -> None:
    op.drop_table("local_recount_instructions")
