"""Preserve complaint taxonomy provenance and immutable case work history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0012_complaint_catalog_cases"
down_revision: str | None = "0011_normal_turnout"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "complaint_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("election_id", sa.Integer(), sa.ForeignKey("elections.id"), nullable=False),
        sa.Column("code", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("verified_source", sa.Boolean(), nullable=False),
        sa.Column("source_english", sa.String(255), nullable=False),
        sa.Column("reference_page", sa.Integer()),
        sa.Column("is_other", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("election_id", "code", name="uq_complaint_category_code"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "complaint_category_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("complaint_categories.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("label_en", sa.String(255), nullable=False),
        sa.Column("label_tc", sa.String(255), nullable=False),
        sa.Column("label_sc", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("description_required", sa.Boolean(), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.UniqueConstraint("category_id", "revision", name="uq_complaint_category_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_complaint_category_revision"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "complaint_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), nullable=False),
        sa.Column("ever_submitted", sa.Boolean(), nullable=False, server_default="0"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_complaint_cases_station_id", "complaint_cases", ["station_id"])
    op.create_table(
        "complaint_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("complaint_cases.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("case_reference", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("received_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("complaint_categories.id"), nullable=False
        ),
        sa.Column(
            "category_revision_id",
            sa.Integer(),
            sa.ForeignKey("complaint_category_revisions.id"),
            nullable=False,
        ),
        sa.Column("category_revision", sa.Integer(), nullable=False),
        sa.Column("category_code", sa.String(64), nullable=False),
        sa.Column("category_label_en", sa.String(255), nullable=False),
        sa.Column("category_label_tc", sa.String(255), nullable=False),
        sa.Column("category_label_sc", sa.String(255), nullable=False),
        sa.Column("category_verified_source", sa.Boolean(), nullable=False),
        sa.Column("category_source_english", sa.String(255), nullable=False),
        sa.Column("category_reference_page", sa.Integer()),
        sa.Column("is_other", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("work_status", sa.String(16), nullable=False),
        sa.Column("completed_at", mysql.DATETIME(fsp=6)),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amendment_reason", sa.String(1000), nullable=False),
        sa.UniqueConstraint("case_id", "revision", name="uq_complaint_case_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_complaint_case_revision"),
        sa.CheckConstraint(
            "(work_status = 'in_progress' AND completed_at IS NULL) OR "
            "(work_status = 'completed' AND completed_at IS NOT NULL "
            "AND completed_at >= received_at)",
            name="ck_complaint_completion",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "complaint_references",
        sa.Column(
            "station_id", sa.Integer(), sa.ForeignKey("polling_stations.id"), primary_key=True
        ),
        sa.Column("reference", sa.String(64, collation="utf8mb4_bin"), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("complaint_cases.id"), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "complaint_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("election_id", sa.Integer(), sa.ForeignKey("elections.id"), nullable=False),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("polling_stations.id")),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("entered_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    # Historical migration data stays fixed even when later display labels change.
    seeds = (
        ("9", "Polling arrangements", "投票安排", "投票安排", 61, False),
        ("10", "NCZ arrangements", "NCZ 安排", "NCZ 安排", 61, False),
        (
            "11",
            "Illegal conduct at the polling station (e.g. photo-taking)",
            "投票站內的違法行為（例如拍照）",
            "投票站内的违法行为（例如拍照）",
            61,
            False,
        ),
        (
            "12",
            "Against Returning Officer or his/her staff",
            "針對選舉主任或其職員",
            "针对选举主任或其职员",
            61,
            False,
        ),
        (
            "30",
            "Miscellaneous (please specify nature)",
            "其他（請註明性質）",
            "其他（请注明性质）",
            62,
            True,
        ),
    )
    connection = op.get_bind()
    for code, english, tc, sc, page, other in seeds:
        connection.execute(
            sa.text(
                "INSERT INTO complaint_categories "
                "(election_id, code, verified_source, source_english, reference_page, is_other) "
                "SELECT id, :code, 1, :english, :page, :other FROM elections"
            ),
            {"code": code, "english": english, "page": page, "other": other},
        )
        connection.execute(
            sa.text(
                "INSERT INTO complaint_category_revisions "
                "(category_id, revision, label_en, label_tc, label_sc, enabled, "
                "description_required, entered_at, actor_id) "
                "SELECT id, 1, :english, :tc, :sc, 1, :other, UTC_TIMESTAMP(6), NULL "
                "FROM complaint_categories WHERE code = :code"
            ),
            {"code": code, "english": english, "tc": tc, "sc": sc, "other": other},
        )


def downgrade() -> None:
    op.drop_table("complaint_requests")
    op.drop_table("complaint_references")
    op.drop_table("complaint_revisions")
    op.drop_index("ix_complaint_cases_station_id", table_name="complaint_cases")
    op.drop_table("complaint_cases")
    op.drop_table("complaint_category_revisions")
    op.drop_table("complaint_categories")
