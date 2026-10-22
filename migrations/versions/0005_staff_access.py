"""Add revisioned staff accounts and explicit polling station assignments."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0005_staff_access"
down_revision: str | None = "0004_stations_and_counters"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "accounts", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_table(
        "station_assignments",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_station_assignments_account"
        ),
        sa.ForeignKeyConstraint(
            ["station_id"], ["polling_stations.id"], name="fk_station_assignments_station"
        ),
        sa.PrimaryKeyConstraint("account_id", "station_id", name="pk_station_assignments"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_station_assignments_station_id", "station_assignments", ["station_id"])


def downgrade() -> None:
    op.drop_index("ix_station_assignments_station_id", table_name="station_assignments")
    op.drop_table("station_assignments")
    op.drop_column("accounts", "revision")
