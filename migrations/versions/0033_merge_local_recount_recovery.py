"""Join local recount history with connectivity and paper recovery."""

revision: str = "0033_local_recount_recovery"
down_revision: tuple[str, ...] = (
    "0031_local_recounts",
    "0032_recovery_counting",
)
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
