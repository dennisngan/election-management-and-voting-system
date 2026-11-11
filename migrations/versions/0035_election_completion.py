"""Preserve finalized election outcomes and original lifecycle request receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0035_election_completion"
down_revision = "0034_constituency_recounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "election_completion_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "election_id",
            sa.Integer(),
            sa.ForeignKey("elections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("election_revision", sa.Integer(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("accepted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column(
            "previous_finalization_id",
            sa.Integer(),
            sa.ForeignKey("election_completion_events.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("basis_digest", sa.String(64), nullable=False),
        sa.Column("data", mysql.JSON(), nullable=False),
        sa.UniqueConstraint(
            "election_id",
            "election_revision",
            name="uq_election_completion_event_revision",
        ),
        sa.CheckConstraint(
            "kind IN ('finalization', 'reopening')",
            name="ck_election_completion_event_kind",
        ),
        sa.CheckConstraint("election_revision >= 1", name="ck_election_completion_event_revision"),
        sa.CheckConstraint(
            "(kind = 'finalization' AND previous_finalization_id IS NULL) OR "
            "(kind = 'reopening' AND previous_finalization_id IS NOT NULL "
            "AND char_length(trim(reason)) > 0)",
            name="ck_election_completion_event_predecessor",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_election_completion_events_election_id",
        "election_completion_events",
        ["election_id"],
    )
    op.create_table(
        "election_completion_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id",
            sa.Integer(),
            sa.ForeignKey("elections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("election_completion_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", mysql.JSON(), nullable=False),
        sa.Column("accepted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint(
            "action IN ('finalization', 'reopening')",
            name="ck_election_completion_request_action",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_election_completion_requests_election_id",
        "election_completion_requests",
        ["election_id"],
    )


def downgrade() -> None:
    op.drop_table("election_completion_requests")
    op.drop_table("election_completion_events")
