"""Preserve box identities, handovers and counting-station milestones."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0010_box_handover"
down_revision: str | None = "0009_queue_observations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ballot_boxes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "origin_station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False
        ),
        sa.Column(
            "destination_station_id",
            sa.Integer(),
            sa.ForeignKey("polling_stations.id"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("box_reference", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("seal_reference", sa.String(128), nullable=False),
        sa.Column("prepared_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.UniqueConstraint("origin_station_id", "box_reference", name="uq_box_origin_reference"),
        sa.CheckConstraint(
            "(mode = 'local' AND origin_station_id = destination_station_id) OR "
            "(mode = 'send' AND origin_station_id <> destination_station_id)",
            name="ck_box_mode_destination",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_ballot_boxes_destination_station_id", "ballot_boxes", ["destination_station_id"]
    )
    op.create_table(
        "box_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("box_id", sa.Integer(), sa.ForeignKey("ballot_boxes.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.UniqueConstraint("box_id", "revision", name="uq_box_event_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_box_event_revision"),
        sa.CheckConstraint(
            "kind IN ('prepared', 'departure', 'receipt', 'departure_correction', "
            "'receipt_correction')",
            name="ck_box_event_kind",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "box_milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("box_id", sa.Integer(), sa.ForeignKey("ballot_boxes.id")),
        sa.UniqueConstraint("station_id", "kind", "revision", name="uq_box_milestone_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_box_milestone_revision"),
        sa.CheckConstraint(
            "kind IN ('conversion_complete', 'first_box_opening', "
            "'questionable_determination_start')",
            name="ck_box_milestone_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'first_box_opening' AND box_id IS NOT NULL) OR "
            "(kind <> 'first_box_opening' AND box_id IS NULL)",
            name="ck_box_milestone_box",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "box_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("box_requests")
    op.drop_table("box_milestones")
    op.drop_table("box_events")
    op.drop_index("ix_ballot_boxes_destination_station_id", table_name="ballot_boxes")
    op.drop_table("ballot_boxes")
