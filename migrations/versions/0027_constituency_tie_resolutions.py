"""Bind explicit constituency tie resolutions to complete stable result bases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0027_constituency_ties"
down_revision: str | None = "0025_count_round_selections"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "constituency_tie_resolutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "constituency_id", sa.Integer(), sa.ForeignKey("constituencies.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("accepted_at", DATETIME(fsp=6), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("basis_digest", sa.String(64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("constituency_id", "revision", name="uq_constituency_tie_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_constituency_tie_revision"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_constituency_tie_resolutions_constituency_id",
        "constituency_tie_resolutions",
        ["constituency_id"],
    )
    op.create_table(
        "constituency_result_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column(
            "constituency_id", sa.Integer(), sa.ForeignKey("constituencies.id"), nullable=False
        ),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("constituency_result_requests")
    op.drop_table("constituency_tie_resolutions")
