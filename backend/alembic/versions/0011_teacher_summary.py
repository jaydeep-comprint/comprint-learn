"""Teacher AI summaries (spec 011): teacher_summary, and an index for remediations by creation time.

Revision ID: 0011_teacher_summary
Revises: 0010_assignments
Create Date: 2026-11-05

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_teacher_summary"
down_revision: str | Sequence[str] | None = "0010_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


summary_kind = _enum("teacher_summary_kind", "class", "student")
summary_status = _enum("teacher_summary_status", "pending", "ok", "partial", "failed", "error")
NEW_ENUMS = [summary_kind, summary_status]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _user_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "org_id"],
        ["app_user.id", "app_user.org_id"],
        ondelete="RESTRICT",
        name=name,
    )


def upgrade() -> None:
    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind)

    op.create_table(
        "teacher_summary",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("class_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=True),
        sa.Column("kind", summary_kind, nullable=False),
        sa.Column("window", sa.Text(), nullable=False),
        sa.Column("status", summary_status, nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("pseudonyms", postgresql.JSONB(), nullable=False),
        sa.Column("facts_hash", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=True),
        sa.Column("dropped", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", _uuid(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("calls", sa.SmallInteger(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_teacher_summary"),
        sa.UniqueConstraint("id", "org_id", name="uq_teacher_summary_id_org_id"),
        sa.CheckConstraint(
            "\"window\" IN ('7d', '30d', 'all')", name="ck_teacher_summary_window"
        ),
        sa.CheckConstraint(
            "(kind = 'student') = (student_id IS NOT NULL)",
            name="ck_teacher_summary_student_iff_student_kind",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            ondelete="RESTRICT",
            name="fk_teacher_summary_org_id_organization",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "org_id"],
            ["school_class.id", "school_class.org_id"],
            ondelete="RESTRICT",
            name="fk_teacher_summary_class_id_school_class",
        ),
        _user_fk("student_id", "fk_teacher_summary_student_app_user"),
        _user_fk("created_by", "fk_teacher_summary_created_by_app_user"),
    )
    op.create_index("ix_teacher_summary_org_id", "teacher_summary", ["org_id"])
    op.create_index(
        "ix_teacher_summary_target",
        "teacher_summary",
        ["org_id", "class_id", "kind", "student_id", "window", sa.text("created_at DESC")],
    )
    op.create_index("ix_teacher_summary_created_by_day", "teacher_summary", ["created_by", "day"])
    op.create_index("ix_teacher_summary_org_id_day", "teacher_summary", ["org_id", "day"])
    op.create_index("ix_remediation_org_id_created_at", "remediation", ["org_id", "created_at"])

    op.execute("ALTER TABLE public.teacher_summary ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_remediation_org_id_created_at", table_name="remediation")
    op.drop_table("teacher_summary")
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind)
