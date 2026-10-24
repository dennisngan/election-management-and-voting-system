"""Retain the source and interval coverage selected for each turnout revision."""

import sqlalchemy as sa
from alembic import op

revision: str = "0019_turnout_source_basis"
down_revision: str | None = "0018_epr_fallback"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("turnout_records", sa.Column(
        "provenance", sa.String(32), server_default="external_manual", nullable=False,
    ))
    op.add_column("turnout_records", sa.Column("source_basis", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("turnout_records", "source_basis")
    op.drop_column("turnout_records", "provenance")
