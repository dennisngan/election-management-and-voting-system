"""Allow immutable count submission and approval revisions."""

from alembic import op

revision: str = "0024_count_round_workflow"
down_revision: str | None = "0023_f2_reason_catalog"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_count_round_status", "count_round_revisions", type_="check")
    op.create_check_constraint(
        "ck_count_round_status",
        "count_round_revisions",
        "status IN ('draft', 'submitted', 'approved')",
    )


def downgrade() -> None:
    # Let MySQL reject incompatible retained statuses rather than delete history.
    op.create_check_constraint(
        "ck_count_round_draft_only", "count_round_revisions", "status = 'draft'"
    )
    op.drop_constraint("ck_count_round_status", "count_round_revisions", type_="check")
    op.drop_constraint("ck_count_round_draft_only", "count_round_revisions", type_="check")
    op.create_check_constraint("ck_count_round_status", "count_round_revisions", "status = 'draft'")
