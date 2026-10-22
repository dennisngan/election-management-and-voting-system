"""Add replay keys to configuration creates without replacing an applied migration."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_configuration_replay_keys"
down_revision: str | None = "0002_election_configuration"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = ("elections", "constituencies", "candidates")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("request_id", sa.String(36), nullable=True))
        op.add_column(table, sa.Column("creation_digest", sa.String(64), nullable=True))
        # Pre-key rows have no client request to replay. Give each one an independent key.
        op.execute(
            sa.text(
                f"UPDATE {table} SET request_id = UUID(), "
                "creation_digest = SHA2(CONCAT('pre-replay-key:', id), 256)"
            )
        )
        op.alter_column(table, "request_id", existing_type=sa.String(36), nullable=False)
        op.alter_column(table, "creation_digest", existing_type=sa.String(64), nullable=False)
        op.create_unique_constraint(f"uq_{table}_request_id", table, ["request_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_constraint(f"uq_{table}_request_id", table, type_="unique")
        op.drop_column(table, "creation_digest")
        op.drop_column(table, "request_id")
