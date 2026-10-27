"""Merge the independent discrepancy, result and backup revisions."""

revision: str = "0030_counting_results_backups"
down_revision: tuple[str, ...] = (
    "0026_count_physical_decisions",
    "0027_constituency_ties",
    "0028_server_backups",
)
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
