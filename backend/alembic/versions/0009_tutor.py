"""AI tutor (spec 009): tutor_session (one thread per question shown) and tutor_message.

Revision ID: 0009_tutor
Revises: 0008_reviews_quizzes
Create Date: 2026-11-05

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_tutor"
down_revision: str | Sequence[str] | None = "0008_reviews_quizzes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


tutor_role = _enum("tutor_role", "student", "tutor")
tutor_kind = _enum("tutor_kind", "hint", "chat")
tutor_mode = _enum("tutor_mode", "before", "after")
tutor_category = _enum("tutor_category", "ok", "needs_hint", "off_topic", "safety")
tutor_status = _enum(
    "tutor_status", "pending", "ok", "guarded", "fallback", "safety", "refused", "error", "late"
)
NEW_ENUMS = [tutor_role, tutor_kind, tutor_mode, tutor_category, tutor_status]

TABLES = ["tutor_session", "tutor_message"]


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tenant(table: str) -> list[sa.ForeignKeyConstraint]:
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


def _tenant_fk(column: str, table: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "org_id"],
        [f"{target}.id", f"{target}.org_id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{column}_{target}",
    )


def _content_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], ondelete="RESTRICT", name=f"fk_{table}_{column}_{target}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind)

    op.create_table(
        "tutor_session",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("practice_session_id", _uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("item_id", _uuid(), nullable=False),
        sa.Column("item_version", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("hints_used", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("chat_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tutor_session"),
        sa.UniqueConstraint("id", "org_id", name="uq_tutor_session_id_org_id"),
        sa.CheckConstraint("hints_used BETWEEN 0 AND 3", name="ck_tutor_session_hints_used"),
        sa.CheckConstraint("chat_count >= 0", name="ck_tutor_session_chat_count"),
        *_tenant("tutor_session"),
        _tenant_fk("practice_session_id", "tutor_session", "practice_session"),
        _content_fk("tutor_session", "item_id", "item"),
    )
    op.create_index("ix_tutor_session_org_id", "tutor_session", ["org_id"])
    op.create_index(
        "uq_tutor_session_question",
        "tutor_session",
        ["practice_session_id", "position", "item_id", "seed"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "tutor_message",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tutor_session_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("role", tutor_role, nullable=False),
        sa.Column("kind", tutor_kind, nullable=False),
        sa.Column("mode", tutor_mode, nullable=False),
        sa.Column("rung", sa.SmallInteger(), nullable=True),
        sa.Column("category", tutor_category, nullable=True),
        sa.Column("status", tutor_status, nullable=False),
        sa.Column("flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("link_concept_id", _uuid(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        _now("created_at"),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tutor_message"),
        sa.CheckConstraint("rung IS NULL OR rung BETWEEN 1 AND 3", name="ck_tutor_message_rung"),
        sa.CheckConstraint(
            "(kind = 'hint') = (rung IS NOT NULL)", name="ck_tutor_message_rung_iff_hint"
        ),
        *_tenant("tutor_message"),
        _tenant_fk("tutor_session_id", "tutor_message", "tutor_session"),
        _content_fk("tutor_message", "link_concept_id", "concept"),
    )
    op.create_index("ix_tutor_message_org_id", "tutor_message", ["org_id"])
    op.create_index("ix_tutor_message_student_id_day", "tutor_message", ["student_id", "day"])
    op.create_index("ix_tutor_message_tutor_session_id", "tutor_message", ["tutor_session_id"])
    op.create_index(
        "ix_tutor_message_flagged",
        "tutor_message",
        ["flagged"],
        postgresql_where=sa.text("flagged"),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("tutor_message")
    op.drop_table("tutor_session")
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind)
