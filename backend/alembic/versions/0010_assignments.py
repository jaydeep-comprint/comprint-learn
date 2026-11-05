"""Teacher assignments (spec 010): assignment, assignment_concept, assignment_student.

Revision ID: 0010_assignments
Revises: 0009_tutor
Create Date: 2026-11-05

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_assignments"
down_revision: str | Sequence[str] | None = "0009_tutor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["assignment", "assignment_concept", "assignment_student"]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["org_id"], ["organization.id"], ondelete="RESTRICT", name=f"fk_{table}_org_id_organization"
    )


def _assignment_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["assignment_id", "org_id"],
        ["assignment.id", "assignment.org_id"],
        ondelete="CASCADE",
        name=f"fk_{table}_assignment_id_assignment",
    )


def upgrade() -> None:
    op.create_table(
        "assignment",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("class_id", _uuid(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("all_students", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", _uuid(), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assignment"),
        sa.UniqueConstraint("id", "org_id", name="uq_assignment_id_org_id"),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 200", name="ck_assignment_note_length"
        ),
        _org_fk("assignment"),
        sa.ForeignKeyConstraint(
            ["class_id", "org_id"],
            ["school_class.id", "school_class.org_id"],
            ondelete="RESTRICT",
            name="fk_assignment_class_id_school_class",
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="RESTRICT",
            name="fk_assignment_created_by_app_user",
        ),
    )
    op.create_index("ix_assignment_org_id", "assignment", ["org_id"])
    op.create_index(
        "ix_assignment_class_live",
        "assignment",
        ["org_id", "class_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "assignment_concept",
        sa.Column("assignment_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("assignment_id", "concept_id", name="pk_assignment_concept"),
        _org_fk("assignment_concept"),
        _assignment_fk("assignment_concept"),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concept.id"],
            ondelete="RESTRICT",
            name="fk_assignment_concept_concept_id_concept",
        ),
    )
    op.create_index("ix_assignment_concept_org_id", "assignment_concept", ["org_id"])

    op.create_table(
        "assignment_student",
        sa.Column("assignment_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("assignment_id", "student_id", name="pk_assignment_student"),
        _org_fk("assignment_student"),
        _assignment_fk("assignment_student"),
        sa.ForeignKeyConstraint(
            ["student_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="RESTRICT",
            name="fk_assignment_student_student_app_user",
        ),
    )
    op.create_index("ix_assignment_student_org_id", "assignment_student", ["org_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("assignment_student")
    op.drop_table("assignment_concept")
    op.drop_table("assignment")
