"""KP flow: concept_state, kp_progress, practice_session, remediation; attempt session link; RLS.

Revision ID: 0005_kp_flow
Revises: 0004_learn
Create Date: 2026-11-04

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_kp_flow"
down_revision: str | Sequence[str] | None = "0004_learn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


concept_status = _enum("concept_status", "in_progress", "learned")
concept_source = _enum("concept_source", "lesson", "diagnostic", "teacher")
kp_status = _enum("kp_status", "not_started", "in_progress", "passed", "failed")
session_kind = _enum("session_kind", "kp", "remediation")
session_status = _enum("session_status", "active", "passed", "failed")
remediation_state = _enum("remediation_state", "review_due", "relearn", "resolved")
remediation_outcome = _enum("remediation_outcome", "review_passed", "relearned")
NEW_ENUMS = [
    concept_status,
    concept_source,
    kp_status,
    session_kind,
    session_status,
    remediation_state,
    remediation_outcome,
]

TABLES = ["concept_state", "kp_progress", "remediation", "practice_session"]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _tenant(table: str) -> list[sa.ForeignKeyConstraint]:
    """org_id FK + composite student FK (the DB rejects a student from another school)."""
    return [
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_org_id_organization",
        ),
        sa.ForeignKeyConstraint(
            ["student_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_student_app_user",
        ),
    ]


def _content_fk(column: str, table: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], ondelete="RESTRICT", name=f"fk_{table}_{column}_{target}"
    )


def _tenant_fk(column: str, table: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "org_id"],
        [f"{target}.id", f"{target}.org_id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{column}_{target}",
    )


def upgrade() -> None:
    # A value added by ALTER TYPE can't be used in the same transaction (the attempt CHECK below
    # uses 'kp'/'remediation'), so commit these first.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE attempt_context ADD VALUE IF NOT EXISTS 'kp'")
        op.execute("ALTER TYPE attempt_context ADD VALUE IF NOT EXISTS 'remediation'")
        op.execute("ALTER TYPE study_activity ADD VALUE IF NOT EXISTS 'practice'")

    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind)

    op.create_table(
        "concept_state",
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("status", concept_status, nullable=False),
        sa.Column("source", concept_source, nullable=False),
        _ts("learned_at"),
        sa.Column("relearn_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("student_id", "concept_id", name="pk_concept_state"),
        *_tenant("concept_state"),
        _content_fk("concept_id", "concept_state", "concept"),
    )
    op.create_index("ix_concept_state_org_id", "concept_state", ["org_id"])

    op.create_table(
        "kp_progress",
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("kp_id", _uuid(), nullable=False),
        sa.Column("status", kp_status, nullable=False),
        sa.Column("fail_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _ts("passed_at"),
        _ts("failed_at"),
        _ts("reopen_at"),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("student_id", "kp_id", name="pk_kp_progress"),
        *_tenant("kp_progress"),
        _content_fk("kp_id", "kp_progress", "knowledge_point"),
    )
    op.create_index("ix_kp_progress_org_id", "kp_progress", ["org_id"])

    op.create_table(
        "remediation",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("kp_id", _uuid(), nullable=False),
        sa.Column("prereq_concept_id", _uuid(), nullable=False),
        sa.Column("state", remediation_state, nullable=False),
        sa.Column("outcome", remediation_outcome, nullable=True),
        _now("created_at"),
        _ts("resolved_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_remediation"),
        sa.UniqueConstraint("id", "org_id", name="uq_remediation_id_org_id"),
        *_tenant("remediation"),
        _content_fk("kp_id", "remediation", "knowledge_point"),
        _content_fk("prereq_concept_id", "remediation", "concept"),
    )
    op.create_index("ix_remediation_org_id", "remediation", ["org_id"])
    op.create_index(
        "uq_remediation_open",
        "remediation",
        ["student_id", "kp_id", "prereq_concept_id"],
        unique=True,
        postgresql_where=sa.text("state <> 'resolved'"),
    )

    op.create_table(
        "practice_session",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("kind", session_kind, nullable=False),
        sa.Column("kp_id", _uuid(), nullable=True),
        sa.Column("remediation_id", _uuid(), nullable=True),
        sa.Column("status", session_status, nullable=False),
        sa.Column("current_item_id", _uuid(), nullable=True),
        sa.Column("current_seed", sa.Integer(), nullable=True),
        sa.Column("current_position", sa.SmallInteger(), nullable=False),
        _ts("current_served_at"),
        _now("started_at"),
        _ts("ended_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_practice_session"),
        sa.UniqueConstraint("id", "org_id", name="uq_practice_session_id_org_id"),
        sa.CheckConstraint(
            "(kind = 'kp') = (kp_id IS NOT NULL) "
            "AND (kind = 'remediation') = (remediation_id IS NOT NULL)",
            name="ck_practice_session_kind_links",
        ),
        *_tenant("practice_session"),
        _content_fk("kp_id", "practice_session", "knowledge_point"),
        _content_fk("current_item_id", "practice_session", "item"),
        _tenant_fk("remediation_id", "practice_session", "remediation"),
    )
    op.create_index("ix_practice_session_org_id", "practice_session", ["org_id"])
    op.create_index(
        "ix_practice_session_org_student_ended",
        "practice_session",
        ["org_id", "student_id", "ended_at"],
    )
    op.create_index(
        "uq_practice_session_active_kp",
        "practice_session",
        ["student_id", "kp_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND kind = 'kp'"),
    )
    op.create_index(
        "uq_practice_session_active_remediation",
        "practice_session",
        ["remediation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.add_column("attempt", sa.Column("session_id", _uuid(), nullable=True))
    op.add_column("attempt", sa.Column("position", sa.SmallInteger(), nullable=True))
    op.create_foreign_key(
        "fk_attempt_session_id_practice_session",
        "attempt",
        "practice_session",
        ["session_id", "org_id"],
        ["id", "org_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_attempt_session_id_position", "attempt", ["session_id", "position"]
    )
    op.create_check_constraint(
        "ck_attempt_session_iff_practice",
        "attempt",
        "(context IN ('kp', 'remediation')) = (session_id IS NOT NULL)",
    )

    # Deny-all for Supabase's Data API, as in 0002-0004 (tests/test_rls_db.py checks every table).
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    # Nothing 004 opened may become locked: every started lesson is an in-progress concept.
    op.execute(
        """
        INSERT INTO concept_state (org_id, student_id, concept_id, status, source, created_at,
                                   updated_at)
        SELECT org_id, student_id, concept_id, 'in_progress', 'lesson', started_at, updated_at
        FROM lesson_progress
        ON CONFLICT DO NOTHING
        """
    )


def _shrink_enum(name: str, values: list[str], table: str, column: str) -> None:
    """Postgres can't drop enum values: recreate the type with `values` only."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    quoted = ", ".join(f"'{v}'" for v in values)
    op.execute(f"CREATE TYPE {name} AS ENUM ({quoted})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} USING {column}::text::{name}"
    )
    op.execute(f"DROP TYPE {name}_old")


def downgrade() -> None:
    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.drop_constraint("uq_attempt_session_id_position", "attempt", type_="unique")
    op.drop_constraint("fk_attempt_session_id_practice_session", "attempt", type_="foreignkey")
    # Practice data can't be represented before 0005.
    op.execute("DELETE FROM attempt WHERE context IN ('kp', 'remediation')")
    op.execute("DELETE FROM study_time WHERE activity = 'practice'")
    op.drop_column("attempt", "position")
    op.drop_column("attempt", "session_id")
    for table in reversed(TABLES):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind)

    # The partial index's predicate names the enum type, so rebuild it around the type swap.
    op.drop_index("uq_attempt_learn_student_item", table_name="attempt")
    _shrink_enum("attempt_context", ["learn"], "attempt", "context")
    op.create_index(
        "uq_attempt_learn_student_item",
        "attempt",
        ["student_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("context = 'learn'"),
    )
    _shrink_enum("study_activity", ["learn"], "study_time", "activity")
