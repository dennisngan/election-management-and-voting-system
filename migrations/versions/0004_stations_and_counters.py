"""Create polling station arrangements and issuance counters."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0004_stations_and_counters"
down_revision: str | None = "0003_configuration_replay_keys"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "polling_stations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("constituency_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("counting_mode", sa.String(16), nullable=False),
        sa.Column("destination_station_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("creation_digest", sa.String(64), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["constituency_id"], ["constituencies.id"], name="fk_polling_stations_constituency"
        ),
        sa.ForeignKeyConstraint(
            ["destination_station_id"],
            ["polling_stations.id"],
            name="fk_polling_stations_destination",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_polling_stations"),
        sa.UniqueConstraint("request_id", name="uq_polling_stations_request_id"),
        sa.UniqueConstraint(
            "constituency_id", "code", name="uq_polling_stations_constituency_code"
        ),
        # MySQL CHECK cannot use the auto-increment id. Self destinations are rejected
        # by the API under the election lock; this CHECK enforces mode/destination shape.
        sa.CheckConstraint(
            "(counting_mode = 'local' AND destination_station_id IS NULL) OR "
            "(counting_mode = 'send' AND destination_station_id IS NOT NULL)",
            name="ck_polling_stations_counting_arrangement",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_polling_stations_constituency_id", "polling_stations", ["constituency_id"])
    op.create_index(
        "ix_polling_stations_destination_station_id", "polling_stations", ["destination_station_id"]
    )
    op.create_table(
        "issuance_counters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("creation_digest", sa.String(64), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["station_id"], ["polling_stations.id"], name="fk_issuance_counters_station"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_issuance_counters"),
        sa.UniqueConstraint("request_id", name="uq_issuance_counters_request_id"),
        sa.UniqueConstraint("station_id", "code", name="uq_issuance_counters_station_code"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_issuance_counters_station_id", "issuance_counters", ["station_id"])


def downgrade() -> None:
    op.drop_index("ix_issuance_counters_station_id", table_name="issuance_counters")
    op.drop_table("issuance_counters")
    op.drop_index("ix_polling_stations_destination_station_id", table_name="polling_stations")
    op.drop_index("ix_polling_stations_constituency_id", table_name="polling_stations")
    op.drop_table("polling_stations")
