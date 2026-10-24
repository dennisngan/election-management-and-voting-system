"""Preserve F1 count-round drafts and revisioned invalid-ballot reasons."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision: str = "0022_f1_count_rounds"
down_revision: str | None = "0021_received_box_scopes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "invalid_ballot_reasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("election_id", sa.Integer(), sa.ForeignKey("elections.id"), nullable=False),
        sa.Column("code", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("stage", sa.String(8), nullable=False),
        sa.Column("verified_source", sa.Boolean(), nullable=False),
        sa.Column("source_english", sa.String(512), nullable=False),
        sa.Column("source_letter", sa.String(8)),
        sa.Column("reference_page", sa.Integer()),
        sa.Column("reference_printed_page", sa.Integer()),
        sa.Column("is_other", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("election_id", "code", name="uq_invalid_reason_code"),
        sa.CheckConstraint("stage IN ('f1', 'f2')", name="ck_invalid_reason_stage"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_invalid_ballot_reasons_election_id", "invalid_ballot_reasons", ["election_id"]
    )
    op.create_table(
        "invalid_ballot_reason_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reason_id", sa.Integer(), sa.ForeignKey("invalid_ballot_reasons.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("label_en", sa.String(512), nullable=False),
        sa.Column("label_tc", sa.String(512), nullable=False),
        sa.Column("label_sc", sa.String(512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("explanation_required", sa.Boolean(), nullable=False),
        sa.Column("entered_at", DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.UniqueConstraint("reason_id", "revision", name="uq_invalid_reason_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_invalid_reason_revision"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_invalid_ballot_reason_revisions_reason_id",
        "invalid_ballot_reason_revisions",
        ["reason_id"],
    )
    op.create_table(
        "invalid_ballot_reason_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("election_id", sa.Integer(), sa.ForeignKey("elections.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "count_rounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_id", sa.Integer(), sa.ForeignKey("counting_scopes.id"), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.UniqueConstraint("scope_id", "round_number", name="uq_count_scope_round"),
        sa.CheckConstraint("round_number >= 1", name="ck_count_round_number"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_count_rounds_scope_id", "count_rounds", ["scope_id"])
    op.create_table(
        "count_round_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("count_rounds.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("event_at", DATETIME(fsp=6), nullable=False),
        sa.Column("entered_at", DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False),
        sa.Column("amendment_reason", sa.String(2000), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("round_id", "revision", name="uq_count_round_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_count_round_revision"),
        sa.CheckConstraint("status = 'draft'", name="ck_count_round_status"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_count_round_revisions_round_id", "count_round_revisions", ["round_id"])
    op.create_table(
        "count_round_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # Keep historical migration seeds fixed when editable catalog labels later change.
    seeds = (
        {
            "code": "gc-f1-a",
            "stage": "f1",
            "label_en": "Endorsed with the words “重複” and “TENDERED”",
            "label_tc": "註有「重複」及「TENDERED」字樣",
            "label_sc": "注有“重複”及“TENDERED”字样",
            "source_english": "Endorsed with the words “重複” and “TENDERED”",
            "source_letter": "a",
            "reference_page": 114,
            "reference_printed_page": 115,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "gc-f1-b",
            "stage": "f1",
            "label_en": (
                "Endorsed with the words “損壞” and “SPOILT” and has/have been "
                "mistakenly put into the ballot box"
            ),
            "label_tc": "註有「損壞」及「SPOILT」字樣，並被誤放入票箱",
            "label_sc": "注有“損壞”及“SPOILT”字样，并被误放入票箱",
            "source_english": (
                "Endorsed with the words “損壞” and “SPOILT” and has/have been "
                "mistakenly put into the ballot box"
            ),
            "source_letter": "b",
            "reference_page": 114,
            "reference_printed_page": 115,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "gc-f1-c",
            "stage": "f1",
            "label_en": (
                "Endorsed with the words “未用” and “UNUSED” and has/have been "
                "mistakenly put into the ballot box"
            ),
            "label_tc": "註有「未用」及「UNUSED」字樣，並被誤放入票箱",
            "label_sc": "注有“未用”及“UNUSED”字样，并被误放入票箱",
            "source_english": (
                "Endorsed with the words “未用” and “UNUSED” and has/have been "
                "mistakenly put into the ballot box"
            ),
            "source_letter": "c",
            "reference_page": 114,
            "reference_printed_page": 115,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "gc-f1-d",
            "stage": "f1",
            "label_en": "Unmarked",
            "label_tc": "沒有填劃",
            "label_sc": "没有填划",
            "source_english": "Unmarked",
            "source_letter": "d",
            "reference_page": 114,
            "reference_printed_page": 115,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "gc-f1-e",
            "stage": "f1",
            "label_en": "Not marked by the chop provided at the polling station (clearly invalid)",
            "label_tc": "並非用投票站提供的印章填劃（明顯無效）",
            "label_sc": "并非用投票站提供的印章填划（明显无效）",
            "source_english": "Not marked by the chop provided at the polling station (clearly "
            "invalid)",
            "source_letter": "e",
            "reference_page": 114,
            "reference_printed_page": 115,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "gc-f1-f",
            "stage": "f1",
            "label_en": "Contains votes for more than 1 candidate",
            "label_tc": "投票予多於 1 名候選人",
            "label_sc": "投票给超过 1 名候选人",
            "source_english": "Contains votes for more than 1 candidate",
            "source_letter": "f",
            "reference_page": 123,
            "reference_printed_page": 124,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "gc-f1-g",
            "stage": "f1",
            "label_en": "Contains a vote for a candidate whose name thereon is crossed out",
            "label_tc": "投票予選票上姓名已被劃去的候選人",
            "label_sc": "投票给选票上姓名已被划去的候选人",
            "source_english": "Contains a vote for a candidate whose name thereon is crossed out",
            "source_letter": "g",
            "reference_page": 123,
            "reference_printed_page": 124,
            "verified_source": True,
            "translation_provenance": "project_translation",
            "is_other": False,
            "explanation_required": False,
        },
        {
            "code": "other-f1",
            "stage": "f1",
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
    connection = op.get_bind()
    for seed in seeds:
        connection.execute(
            sa.text(
                "INSERT INTO invalid_ballot_reasons "
                "(election_id, code, stage, verified_source, source_english, source_letter, "
                "reference_page, reference_printed_page, is_other) "
                "SELECT id, :code, :stage, :verified_source, :source_english, :source_letter, "
                ":reference_page, :reference_printed_page, :is_other FROM elections"
            ),
            seed,
        )
        connection.execute(
            sa.text(
                "INSERT INTO invalid_ballot_reason_revisions "
                "(reason_id, revision, label_en, label_tc, label_sc, enabled, "
                "explanation_required, entered_at, actor_id) "
                "SELECT id, 1, :label_en, :label_tc, :label_sc, 1, "
                ":explanation_required, UTC_TIMESTAMP(6), NULL "
                "FROM invalid_ballot_reasons WHERE code = :code"
            ),
            seed,
        )


def downgrade() -> None:
    op.drop_table("count_round_requests")
    op.drop_table("count_round_revisions")
    op.drop_table("count_rounds")
    op.drop_table("invalid_ballot_reason_requests")
    op.drop_table("invalid_ballot_reason_revisions")
    op.drop_table("invalid_ballot_reasons")
