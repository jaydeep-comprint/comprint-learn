"""XP & gamification (spec 008): xp_event ledger, xp_day snapshot, student_goal; class columns; RLS.

- `xp_event`: append-only, one per ended practice_session (unique `session_id` where not null).
- `xp_day`: per student × IST date × subject: net XP, the frozen goal and when it was met.
- `student_goal`: a student's own daily goal per subject.
- `school_class.daily_goal` (default 15) and `leaderboard_enabled` (default off).

No backfill: every student starts at 0.

Revision ID: 0007_xp
Revises: 0006_practice_formats
Create Date: 2026-11-05

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_xp"
down_revision: str | Sequence[str] | None = "0006_practice_formats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


xp_reason = _enum("xp_reason", "kp", "remediation", "practice")
xp_grade = _enum("xp_grade", "perfect", "passed", "partial", "poor", "rushed")
class_subject = _enum("class_subject", "maths", "physics", "python")  # exists since 0002
NEW_ENUMS = [xp_reason, xp_grade]

TABLES = ["xp_event", "xp_day", "student_goal"]
GOAL_CHECK = "BETWEEN 5 AND 60 AND {col} % 5 = 0"


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


def upgrade() -> None:
    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind)

    op.create_table(
        "xp_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("session_id", _uuid(), nullable=True),
        sa.Column("reason", xp_reason, nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("subject", class_subject, nullable=False),
        sa.Column("amount", sa.SmallInteger(), nullable=False),
        sa.Column("grade", xp_grade, nullable=False),
        sa.Column("base_minutes", sa.Numeric(5, 1), nullable=False),
        sa.Column("answered", sa.SmallInteger(), nullable=False),
        sa.Column("rushed_count", sa.SmallInteger(), nullable=False),
        sa.Column("hints", sa.SmallInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        _now("created_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_xp_event"),
        sa.CheckConstraint("amount BETWEEN -100 AND 500", name="ck_xp_event_amount"),
        *_tenant("xp_event"),
        sa.ForeignKeyConstraint(
            ["session_id", "org_id"],
            ["practice_session.id", "practice_session.org_id"],
            ondelete="RESTRICT",
            name="fk_xp_event_session_id_practice_session",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concept.id"],
            ondelete="RESTRICT",
            name="fk_xp_event_concept_id_concept",
        ),
    )
    op.create_index("ix_xp_event_org_id", "xp_event", ["org_id"])
    op.create_index("ix_xp_event_org_student_day", "xp_event", ["org_id", "student_id", "day"])
    op.create_index(
        "uq_xp_event_session",
        "xp_event",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    op.create_table(
        "xp_day",
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("subject", class_subject, nullable=False),
        sa.Column("xp", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("goal", sa.SmallInteger(), nullable=True),
        sa.Column("met_at", sa.DateTime(timezone=True), nullable=True),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("student_id", "day", "subject", name="pk_xp_day"),
        sa.CheckConstraint("goal BETWEEN 5 AND 60", name="ck_xp_day_goal"),
        *_tenant("xp_day"),
    )
    op.create_index("ix_xp_day_org_id", "xp_day", ["org_id"])

    op.create_table(
        "student_goal",
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("subject", class_subject, nullable=False),
        sa.Column("goal", sa.SmallInteger(), nullable=False),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("student_id", "subject", name="pk_student_goal"),
        sa.CheckConstraint("goal " + GOAL_CHECK.format(col="goal"), name="ck_student_goal_goal"),
        *_tenant("student_goal"),
    )
    op.create_index("ix_student_goal_org_id", "student_goal", ["org_id"])

    op.add_column(
        "school_class",
        sa.Column("daily_goal", sa.SmallInteger(), server_default=sa.text("15"), nullable=False),
    )
    op.add_column(
        "school_class",
        sa.Column(
            "leaderboard_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_school_class_daily_goal",
        "school_class",
        "daily_goal " + GOAL_CHECK.format(col="daily_goal"),
    )

    # Deny-all for Supabase's Data API, as in 0002-0005 (tests/test_rls_db.py checks every table).
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_constraint("ck_school_class_daily_goal", "school_class", type_="check")
    op.drop_column("school_class", "leaderboard_enabled")
    op.drop_column("school_class", "daily_goal")
    for table in reversed(TABLES):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind)
