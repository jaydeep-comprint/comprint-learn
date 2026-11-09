"""Placement (spec 012): class_covered_chapter, diagnostic_session; diagnostic kind/context.

- `attempt_context` and `session_kind` + `diagnostic`; `review_source` + `placed`.
- `practice_session.diagnostic_id` (kind `diagnostic`, one session per diagnostic).
- `concept_state.conditional` (placed on thin evidence; cleared by the first review outcome).

Revision ID: 0012_placement
Revises: 0011_teacher_summary
Create Date: 2026-11-08

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_placement"
down_revision: str | Sequence[str] | None = "0011_teacher_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

diagnostic_status = postgresql.ENUM(
    "sent", "active", "finished", "cancelled", name="diagnostic_status", create_type=False
)
NEW_ENUMS = [diagnostic_status]

TABLES = ["class_covered_chapter", "diagnostic_session"]

KIND_LINKS_011 = (
    "(kind = 'kp') = (kp_id IS NOT NULL) AND (kind = 'remediation') = (remediation_id IS NOT NULL)"
    " AND (kind IN ('practice', 'review')) = (concept_id IS NOT NULL)"
    " AND (kind = 'quiz') = (quiz_id IS NOT NULL)"
)
KIND_LINKS_012 = KIND_LINKS_011 + " AND (kind = 'diagnostic') = (diagnostic_id IS NOT NULL)"
SESSION_CHECK_011 = (
    "(context IN ('kp', 'remediation', 'practice', 'review', 'quiz')) = (session_id IS NOT NULL)"
)
SESSION_CHECK_012 = (
    "(context IN ('kp', 'remediation', 'practice', 'review', 'quiz', 'diagnostic'))"
    " = (session_id IS NOT NULL)"
)

SESSION_KINDS_011 = ["kp", "remediation", "practice", "review", "quiz"]
CONTEXTS_011 = ["learn", "kp", "remediation", "practice", "review", "quiz"]
REVIEW_SOURCES_011 = [
    "learned",
    "relearned",
    "review",
    "brushup",
    "implicit",
    "quiz_miss",
    "backfill",
]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["org_id"], ["organization.id"], ondelete="RESTRICT", name=f"fk_{table}_org_id_organization"
    )


def _pair_fk(table: str, column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "org_id"],
        [f"{target}.id", f"{target}.org_id"],
        ondelete="RESTRICT",
        name=name,
    )


def upgrade() -> None:
    # New values can't be used in the transaction that adds them (the checks below use them).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE attempt_context ADD VALUE IF NOT EXISTS 'diagnostic'")
        op.execute("ALTER TYPE session_kind ADD VALUE IF NOT EXISTS 'diagnostic'")
        op.execute("ALTER TYPE review_source ADD VALUE IF NOT EXISTS 'placed'")

    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind)

    op.create_table(
        "class_covered_chapter",
        sa.Column("class_id", _uuid(), nullable=False),
        sa.Column("chapter_id", _uuid(), nullable=False),
        sa.Column("created_by", _uuid(), nullable=False),
        _now("created_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("class_id", "chapter_id", name="pk_class_covered_chapter"),
        _org_fk("class_covered_chapter"),
        _pair_fk(
            "class_covered_chapter",
            "class_id",
            "school_class",
            "fk_class_covered_chapter_class_id_school_class",
        ),
        _pair_fk(
            "class_covered_chapter",
            "created_by",
            "app_user",
            "fk_class_covered_chapter_created_by_app_user",
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapter.id"],
            ondelete="RESTRICT",
            name="fk_class_covered_chapter_chapter_id_chapter",
        ),
    )
    op.create_index("ix_class_covered_chapter_org_id", "class_covered_chapter", ["org_id"])

    op.create_table(
        "diagnostic_session",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("class_id", _uuid(), nullable=False),
        sa.Column("status", diagnostic_status, nullable=False),
        sa.Column("sent_by", _uuid(), nullable=False),
        _now("sent_at"),
        _ts("started_at"),
        _ts("finished_at"),
        _ts("cancelled_at"),
        sa.Column("chapter_ids", postgresql.ARRAY(_uuid()), nullable=True),
        sa.Column("range_ids", postgresql.ARRAY(_uuid()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "served_item_ids",
            postgresql.ARRAY(_uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("answered", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_diagnostic_session"),
        sa.UniqueConstraint("id", "org_id", name="uq_diagnostic_session_id_org_id"),
        _org_fk("diagnostic_session"),
        _pair_fk(
            "diagnostic_session", "student_id", "app_user", "fk_diagnostic_session_student_app_user"
        ),
        _pair_fk(
            "diagnostic_session",
            "class_id",
            "school_class",
            "fk_diagnostic_session_class_id_school_class",
        ),
        _pair_fk(
            "diagnostic_session", "sent_by", "app_user", "fk_diagnostic_session_sent_by_app_user"
        ),
    )
    op.create_index("ix_diagnostic_session_org_id", "diagnostic_session", ["org_id"])
    op.create_index(
        "ix_diagnostic_session_class",
        "diagnostic_session",
        ["org_id", "class_id", "student_id", "sent_at"],
    )
    op.create_index(
        "uq_diagnostic_session_open",
        "diagnostic_session",
        ["student_id", "class_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('sent', 'active')"),
    )

    op.add_column("practice_session", sa.Column("diagnostic_id", _uuid(), nullable=True))
    op.create_foreign_key(
        "fk_practice_session_diagnostic_id_diagnostic_session",
        "practice_session",
        "diagnostic_session",
        ["diagnostic_id", "org_id"],
        ["id", "org_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_practice_session_kind_links", "practice_session", type_="check")
    op.create_check_constraint("ck_practice_session_kind_links", "practice_session", KIND_LINKS_012)
    op.create_index(
        "uq_practice_session_diagnostic",
        "practice_session",
        ["diagnostic_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'diagnostic'"),
    )

    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.create_check_constraint("ck_attempt_session_iff_practice", "attempt", SESSION_CHECK_012)

    op.add_column(
        "concept_state",
        sa.Column("conditional", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def _shrink_enum(name: str, values: list[str], table: str, column: str) -> None:
    """Postgres can't drop enum values: recreate the type with `values` only."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    quoted = ", ".join(f"'{v}'" for v in values)
    op.execute(f"CREATE TYPE {name} AS ENUM ({quoted})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} USING {column}::text::{name}"
    )
    op.execute(f"DROP TYPE {name}_old")


# Partial indexes whose predicates compare `practice_session.kind` (dropped around the shrink).
SESSION_KIND_INDEXES: list[tuple[str, list[str], str]] = [
    ("uq_practice_session_active_kp", ["student_id", "kp_id"], "status = 'active' AND kind = 'kp'"),
    (
        "uq_practice_session_active_practice",
        ["student_id", "concept_id"],
        "status = 'active' AND kind = 'practice'",
    ),
    (
        "uq_practice_session_active_review",
        ["student_id", "concept_id"],
        "status = 'active' AND kind = 'review'",
    ),
    ("uq_practice_session_quiz", ["quiz_id"], "kind = 'quiz'"),
]


def downgrade() -> None:
    # Placement data can't be represented before 0012.
    op.execute("DELETE FROM attempt WHERE context = 'diagnostic'")
    op.execute("DELETE FROM practice_session WHERE kind = 'diagnostic'")
    op.execute("UPDATE review_log SET source = 'learned' WHERE source = 'placed'")

    op.drop_column("concept_state", "conditional")

    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.drop_index("uq_attempt_learn_student_item", table_name="attempt")
    _shrink_enum("attempt_context", CONTEXTS_011, "attempt", "context")
    op.create_index(
        "uq_attempt_learn_student_item",
        "attempt",
        ["student_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("context = 'learn'"),
    )
    op.create_check_constraint("ck_attempt_session_iff_practice", "attempt", SESSION_CHECK_011)

    op.drop_index("uq_practice_session_diagnostic", table_name="practice_session")
    for name, _cols, _where in SESSION_KIND_INDEXES:
        op.drop_index(name, table_name="practice_session")
    op.drop_constraint("ck_practice_session_kind_links", "practice_session", type_="check")
    op.drop_constraint(
        "fk_practice_session_diagnostic_id_diagnostic_session",
        "practice_session",
        type_="foreignkey",
    )
    op.drop_column("practice_session", "diagnostic_id")
    _shrink_enum("session_kind", SESSION_KINDS_011, "practice_session", "kind")
    op.create_check_constraint("ck_practice_session_kind_links", "practice_session", KIND_LINKS_011)
    for name, cols, where in SESSION_KIND_INDEXES:
        op.create_index(
            name, "practice_session", cols, unique=True, postgresql_where=sa.text(where)
        )

    _shrink_enum("review_source", REVIEW_SOURCES_011, "review_log", "source")

    op.drop_table("diagnostic_session")
    op.drop_table("class_covered_chapter")
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind)
