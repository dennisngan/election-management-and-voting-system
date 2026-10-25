"""Preserve explicit versioned selection of exact approved count revisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0025_count_round_selections"
down_revision: str | None = "0024_count_round_workflow"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "count_round_selections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_id", sa.Integer(), sa.ForeignKey("counting_scopes.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "round_revision_id",
            sa.Integer(),
            sa.ForeignKey("count_round_revisions.id"),
            nullable=False,
        ),
        sa.Column("selected_at", DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.UniqueConstraint("scope_id", "revision", name="uq_count_scope_selection_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_count_scope_selection_revision"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_count_round_selections_scope_id", "count_round_selections", ["scope_id"])
    op.create_index(
        "ix_count_round_selections_round_revision_id",
        "count_round_selections",
        ["round_revision_id"],
    )


def downgrade() -> None:
    op.drop_table("count_round_selections")
