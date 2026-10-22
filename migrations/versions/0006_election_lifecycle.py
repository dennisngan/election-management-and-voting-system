"""Create election schedules and the single active-election pointer."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0006_election_lifecycle"
down_revision: str | None = "0005_staff_access"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "election_schedules",
        sa.Column("election_id", sa.Integer(), nullable=False),
        sa.Column("election_date", sa.Date(), nullable=False),
        sa.Column("planned_opening_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("planned_closing_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reporting_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["election_id"], ["elections.id"], name="fk_election_schedules_election"
        ),
        sa.PrimaryKeyConstraint("election_id", name="pk_election_schedules"),
        sa.CheckConstraint(
            "reporting_interval_minutes BETWEEN 1 AND 1440",
            name="ck_election_schedules_reporting_interval",
        ),
        sa.CheckConstraint(
            "planned_closing_at > planned_opening_at", name="ck_election_schedules_ordered_times"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "active_election",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("election_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["election_id"], ["elections.id"], name="fk_active_election_election"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_active_election"),
        sa.CheckConstraint("id = 1", name="ck_active_election_singleton"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    singleton = sa.table(
        "active_election", sa.column("id"), sa.column("election_id"), sa.column("revision")
    )
    op.bulk_insert(singleton, [{"id": 1, "election_id": None, "revision": 1}])


def downgrade() -> None:
    op.drop_table("active_election")
    op.drop_table("election_schedules")
