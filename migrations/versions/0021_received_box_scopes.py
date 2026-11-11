"""Freeze received-box counting scopes and prevent duplicate box membership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0021_received_box_scopes"
down_revision: str | None = "0020_p18_accounting"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "counting_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("reference", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.UniqueConstraint("station_id", "reference", name="uq_scope_station_reference"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_counting_scopes_station_id", "counting_scopes", ["station_id"])
    op.create_table(
        "counting_scope_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_id", sa.Integer(), sa.ForeignKey("counting_scopes.id"), nullable=False),
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
        sa.UniqueConstraint("scope_id", "revision", name="uq_scope_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_scope_revision"),
        sa.CheckConstraint("status IN ('draft', 'submitted')", name="ck_scope_status"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_counting_scope_revisions_scope_id", "counting_scope_revisions", ["scope_id"]
    )
    op.create_table(
        "counting_scope_boxes",
        sa.Column("box_id", sa.Integer(), sa.ForeignKey("ballot_boxes.id"), primary_key=True),
        sa.Column("scope_id", sa.Integer(), sa.ForeignKey("counting_scopes.id"), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_counting_scope_boxes_scope_id", "counting_scope_boxes", ["scope_id"])
    op.create_table(
        "counting_scope_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("counting_scope_requests")
    op.drop_table("counting_scope_boxes")
    op.drop_table("counting_scope_revisions")
    op.drop_table("counting_scopes")
