"""Preserve exact-basis Supervisor physical-discrepancy decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0026_count_physical_decisions"
down_revision: str | None = "0025_count_round_selections"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "count_physical_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("count_rounds.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "round_revision_id",
            sa.Integer(),
            sa.ForeignKey("count_round_revisions.id"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("accepted_at", DATETIME(fsp=6), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "round_id", "source", "revision", name="uq_count_physical_decision_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_count_physical_decision_revision"),
        sa.CheckConstraint(
            "source IN ('stock', 'turnout')", name="ck_count_physical_decision_source"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_count_physical_decisions_round_id", "count_physical_decisions", ["round_id"]
    )
    op.create_index(
        "ix_count_physical_decisions_round_revision_id",
        "count_physical_decisions",
        ["round_revision_id"],
    )


def downgrade() -> None:
    op.drop_table("count_physical_decisions")
