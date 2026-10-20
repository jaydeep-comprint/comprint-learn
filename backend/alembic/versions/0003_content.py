"""Global content: course, chapter, concept, concept_prereq, knowledge_point, kp_key_prereq,
misconception, item; RLS deny-all on each.

Revision ID: 0003_content
Revises: 0002_auth_tenancy
Create Date: 2026-10-20

"""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_content"
down_revision: str | Sequence[str] | None = "0002_auth_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reused from 0002 (a class's course is the course with the class's subject).
class_subject = postgresql.ENUM(
    "maths", "physics", "python", name="class_subject", create_type=False
)
item_kind = postgresql.ENUM(
    "kp_question", "practice", "misconception_check", name="item_kind", create_type=False
)
item_type = postgresql.ENUM(
    "numeric", "expression", "mcq", "multistep", "code", name="item_type", create_type=False
)
bloom_level = postgresql.ENUM(
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
    name="bloom_level",
    create_type=False,
)

TABLES = [
    "course",
    "chapter",
    "concept",
    "concept_prereq",
    "knowledge_point",
    "kp_key_prereq",
    "misconception",
    "item",
]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _content_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _fk(column: str, table: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], ondelete="RESTRICT", name=f"fk_{table}_{column}_{target}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    item_kind.create(bind)
    item_type.create(bind)
    bloom_level.create(bind)

    op.create_table(
        "course",
        *_content_columns(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subject", class_subject, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_course"),
        sa.UniqueConstraint("slug", name="uq_course_slug"),
    )
    op.create_index(
        "uq_course_subject_active",
        "course",
        ["subject"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )

    op.create_table(
        "chapter",
        *_content_columns(),
        sa.Column("course_id", _uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_chapter"),
        sa.UniqueConstraint("course_id", "slug", name="uq_chapter_course_id_slug"),
        sa.CheckConstraint("grade IN (9, 10)", name="ck_chapter_grade"),
        _fk("course_id", "chapter", "course"),
    )

    op.create_table(
        "concept",
        *_content_columns(),
        sa.Column("course_id", _uuid(), nullable=False),
        sa.Column("chapter_id", _uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("intro_md", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_concept"),
        sa.UniqueConstraint("course_id", "slug", name="uq_concept_course_id_slug"),
        _fk("course_id", "concept", "course"),
        _fk("chapter_id", "concept", "chapter"),
    )
    op.create_index("ix_concept_chapter_id", "concept", ["chapter_id"])

    op.create_table(
        "concept_prereq",
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("prereq_id", _uuid(), nullable=False),
        sa.Column("encompassing_weight", sa.Numeric(3, 2), nullable=False),
        sa.PrimaryKeyConstraint("concept_id", "prereq_id", name="pk_concept_prereq"),
        sa.CheckConstraint(
            "encompassing_weight > 0 AND encompassing_weight <= 1",
            name="ck_concept_prereq_weight_range",
        ),
        sa.CheckConstraint("concept_id <> prereq_id", name="ck_concept_prereq_no_self_edge"),
        _fk("concept_id", "concept_prereq", "concept"),
        _fk("prereq_id", "concept_prereq", "concept"),
    )
    op.create_index("ix_concept_prereq_prereq_id", "concept_prereq", ["prereq_id"])

    op.create_table(
        "knowledge_point",
        *_content_columns(),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("worked_example_md", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_point"),
        sa.UniqueConstraint("concept_id", "slug", name="uq_knowledge_point_concept_id_slug"),
        _fk("concept_id", "knowledge_point", "concept"),
    )

    op.create_table(
        "kp_key_prereq",
        sa.Column("kp_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("kp_id", "concept_id", name="pk_kp_key_prereq"),
        _fk("kp_id", "kp_key_prereq", "knowledge_point"),
        _fk("concept_id", "kp_key_prereq", "concept"),
    )
    op.create_index("ix_kp_key_prereq_concept_id", "kp_key_prereq", ["concept_id"])

    op.create_table(
        "misconception",
        *_content_columns(),
        sa.Column("course_id", _uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_misconception"),
        sa.UniqueConstraint("course_id", "slug", name="uq_misconception_course_id_slug"),
        _fk("course_id", "misconception", "course"),
    )

    op.create_table(
        "item",
        *_content_columns(),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("kp_id", _uuid(), nullable=True),
        sa.Column("kind", item_kind, nullable=False),
        sa.Column("type", item_type, nullable=False),
        sa.Column("bloom_level", bloom_level, nullable=False),
        sa.Column("expected_minutes", sa.Numeric(3, 1), nullable=False),
        sa.Column("has_params", sa.Boolean(), nullable=False),
        sa.Column("public", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_item"),
        sa.UniqueConstraint("concept_id", "slug", name="uq_item_concept_id_slug"),
        sa.CheckConstraint(
            "(kp_id IS NOT NULL) = (kind = 'kp_question')", name="ck_item_kp_iff_kp_question"
        ),
        _fk("concept_id", "item", "concept"),
        _fk("kp_id", "item", "knowledge_point"),
    )
    op.create_index("ix_item_kp_id", "item", ["kp_id"])

    # Deny-all for Supabase's Data API, as in 0002 (tests/test_rls_db.py checks every table).
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    bind = op.get_bind()
    bloom_level.drop(bind)
    item_type.drop(bind)
    item_kind.drop(bind)
