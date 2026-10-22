"""Create draft elections, single-seat constituencies, and constituency-owned candidates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002_election_configuration"
down_revision: str | None = "0001_accounts"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "elections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_elections"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "constituencies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("election_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("choices_per_ballot", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["election_id"], ["elections.id"], name="fk_constituencies_election"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_constituencies"),
        sa.UniqueConstraint("election_id", "code", name="uq_constituencies_election_code"),
        sa.CheckConstraint("seats = 1", name="ck_constituencies_one_seat"),
        sa.CheckConstraint("choices_per_ballot = 1", name="ck_constituencies_one_choice"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_constituencies_election_id", "constituencies", ["election_id"])
    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("constituency_id", sa.Integer(), nullable=False),
        sa.Column("ballot_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["constituency_id"], ["constituencies.id"], name="fk_candidates_constituency"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidates"),
        sa.UniqueConstraint(
            "constituency_id", "ballot_number", name="uq_candidates_constituency_ballot_number"
        ),
        sa.CheckConstraint("ballot_number > 0", name="ck_candidates_positive_ballot_number"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_candidates_constituency_id", "candidates", ["constituency_id"])


def downgrade() -> None:
    op.drop_index("ix_candidates_constituency_id", table_name="candidates")
    op.drop_table("candidates")
    op.drop_index("ix_constituencies_election_id", table_name="constituencies")
    op.drop_table("constituencies")
    op.drop_table("elections")
