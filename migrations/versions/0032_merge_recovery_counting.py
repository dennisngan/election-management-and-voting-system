"""Join the independent outage recovery and reviewed counting schema branches."""

revision: str = "0032_recovery_counting"
down_revision: tuple[str, ...] = (
    "0030_counting_results_backups",
    "0029_outage_paper_reentry",
)
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
