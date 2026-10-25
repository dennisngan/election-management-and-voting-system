"""Preserve stage-specific reason identities and backfill verified F2 sources."""

import sqlalchemy as sa
from alembic import op

revision: str = "0023_f2_reason_catalog"
down_revision: str | None = "0022_f1_count_rounds"
branch_labels: str | None = None
depends_on: str | None = None

# Freeze migration values independently of later editable project labels.
SEEDS = (
    {
        "code": "gc-f2-h",
        "stage": "f2",
        "label_en": "With writing or mark by which the elector can possibly be identified",
        "label_tc": "載有可能識別選民身分的文字或記號",
        "label_sc": "载有可能识别选民身份的文字或记号",
        "source_english": "With writing or mark by which the elector can possibly be identified",
        "source_letter": "h",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f2-i",
        "stage": "f2",
        "label_en": "Not marked by the chop provided at the polling station (determined as invalid "
        "upon determination of Q-paper)",
        "label_tc": "並非用投票站提供的印章填劃（經問題選票判定後確定為無效）",
        "label_sc": "并非用投票站提供的印章填划（经问题选票判定后确定为无效）",
        "source_english": "Not marked by the chop provided at the polling station (determined as "
        "invalid upon determination of Q-paper)",
        "source_letter": "i",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f2-j",
        "stage": "f2",
        "label_en": "Substantially mutilated",
        "label_tc": "嚴重殘缺",
        "label_sc": "严重残缺",
        "source_english": "Substantially mutilated",
        "source_letter": "j",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f2-k",
        "stage": "f2",
        "label_en": "Void for uncertainty",
        "label_tc": "因不明確而無效",
        "label_sc": "因不明确而无效",
        "source_english": "Void for uncertainty",
        "source_letter": "k",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "other-f2",
        "stage": "f2",
        "label_en": "Other",
        "label_tc": "其他",
        "label_sc": "其他",
        "source_english": "",
        "source_letter": None,
        "reference_page": None,
        "reference_printed_page": None,
        "verified_source": False,
        "translation_provenance": "project_translation",
        "is_other": True,
        "explanation_required": True,
    },
)


def upgrade() -> None:
    op.drop_constraint("uq_invalid_reason_code", "invalid_ballot_reasons", type_="unique")
    op.create_unique_constraint(
        "uq_invalid_reason_stage_code", "invalid_ballot_reasons", ["election_id", "stage", "code"]
    )
    connection = op.get_bind()
    for seed in SEEDS:
        connection.execute(
            sa.text(
                "INSERT INTO invalid_ballot_reasons "
                "(election_id, code, stage, verified_source, source_english, source_letter, "
                "reference_page, reference_printed_page, is_other) "
                "SELECT e.id, :code, :stage, :verified_source, :source_english, :source_letter, "
                ":reference_page, :reference_printed_page, :is_other FROM elections e "
                "WHERE NOT EXISTS (SELECT 1 FROM invalid_ballot_reasons r "
                "WHERE r.election_id = e.id AND r.stage = :stage AND r.code = :code)"
            ),
            seed,
        )
        connection.execute(
            sa.text(
                "INSERT INTO invalid_ballot_reason_revisions "
                "(reason_id, revision, label_en, label_tc, label_sc, enabled, "
                "explanation_required, entered_at, actor_id) "
                "SELECT r.id, 1, :label_en, :label_tc, :label_sc, 1, "
                ":explanation_required, UTC_TIMESTAMP(6), NULL "
                "FROM invalid_ballot_reasons r WHERE r.stage = :stage AND r.code = :code "
                "AND NOT EXISTS (SELECT 1 FROM invalid_ballot_reason_revisions v "
                "WHERE v.reason_id = r.id)"
            ),
            seed,
        )


def downgrade() -> None:
    connection = op.get_bind()
    collision = connection.execute(
        sa.text(
            "SELECT 1 FROM invalid_ballot_reasons GROUP BY election_id, code "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if collision:
        raise RuntimeError("Cannot remove stage identity while cross-stage reason codes coexist")
    op.drop_constraint("uq_invalid_reason_stage_code", "invalid_ballot_reasons", type_="unique")
    op.create_unique_constraint(
        "uq_invalid_reason_code", "invalid_ballot_reasons", ["election_id", "code"]
    )
    # Preserve seeded source identities and their revisions on downgrade.
