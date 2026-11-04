"""Learn layer: attempt, lesson_progress, study_time (tenant-owned); concept.asset_path; RLS on each.

Revision ID: 0004_learn
Revises: 0003_content
Create Date: 2026-11-04

"""

import uuid
from datetime import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_learn"
down_revision: str | Sequence[str] | None = "0003_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

attempt_context = postgresql.ENUM("learn", name="attempt_context", create_type=False)
study_activity = postgresql.ENUM("learn", name="study_activity", create_type=False)

TABLES = ["attempt", "lesson_progress", "study_time"]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


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


def upgrade() -> None:
    bind = op.get_bind()
    attempt_context.create(bind)
    study_activity.create(bind)

    op.add_column(
        "concept", sa.Column("asset_path", sa.Text(), server_default=sa.text("''"), nullable=False)
    )

    op.create_table(
        "attempt",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("item_id", _uuid(), nullable=False),
        sa.Column("item_version", sa.Integer(), nullable=False),
        sa.Column("context", attempt_context, nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("misconception_id", _uuid(), nullable=True),
        sa.Column("time_taken_ms", sa.Integer(), nullable=False),
        sa.Column("hints_used", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _now("created_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_attempt"),
        *_tenant("attempt"),
        _content_fk("item_id", "attempt", "item"),
        _content_fk("misconception_id", "attempt", "misconception"),
    )
    op.create_index("ix_attempt_org_id", "attempt", ["org_id"])
    op.create_index(
        "ix_attempt_org_student_created", "attempt", ["org_id", "student_id", "created_at"]
    )
    op.create_index(
        "uq_attempt_learn_student_item",
        "attempt",
        ["student_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("context = 'learn'"),
    )

    op.create_table(
        "lesson_progress",
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column(
            "seen_steps",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("last_step", sa.Text(), nullable=False),
        _now("started_at"),
        _now("updated_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("student_id", "concept_id", name="pk_lesson_progress"),
        *_tenant("lesson_progress"),
        _content_fk("concept_id", "lesson_progress", "concept"),
    )
    op.create_index("ix_lesson_progress_org_id", "lesson_progress", ["org_id"])

    op.create_table(
        "study_time",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("activity", study_activity, nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("active_seconds", sa.SmallInteger(), nullable=False),
        _now("created_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_study_time"),
        sa.CheckConstraint(
            "active_seconds BETWEEN 1 AND 600", name="ck_study_time_active_seconds_range"
        ),
        *_tenant("study_time"),
        _content_fk("concept_id", "study_time", "concept"),
    )
    op.create_index("ix_study_time_org_id", "study_time", ["org_id"])
    op.create_index(
        "ix_study_time_org_student_created", "study_time", ["org_id", "student_id", "created_at"]
    )

    # Deny-all for Supabase's Data API, as in 0002/0003 (tests/test_rls_db.py checks every table).
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_column("concept", "asset_path")
    bind = op.get_bind()
    study_activity.drop(bind)
    attempt_context.drop(bind)
