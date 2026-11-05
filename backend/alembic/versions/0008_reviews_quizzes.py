"""Reviews + quizzes (spec 007): review_card, review_log, quiz, quiz_item; session/attempt kinds.

- `session_kind`, `attempt_context`, `xp_reason` + `review`, `quiz`.
- `practice_session.quiz_id` (kind `quiz`); `concept_id` now also for kind `review`; one active
  review per student x concept, one session per quiz.
- `xp_event`: unique `(session_id, subject)` (a quiz writes one event per subject).
- Backfill: a card for every learned concept with gradable KP items, as if `learned_at` were a
  first `Good` review (py-fsrs at migration time), logged with source `backfill`.

Revision ID: 0008_reviews_quizzes
Revises: 0007_xp
Create Date: 2026-11-05

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from fsrs import Card, Rating, Scheduler
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_reviews_quizzes"
down_revision: str | Sequence[str] | None = "0007_xp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


review_due_reason = _enum("review_due_reason", "schedule", "quiz_miss")
review_source = _enum(
    "review_source",
    "learned",
    "relearned",
    "review",
    "brushup",
    "implicit",
    "quiz_miss",
    "backfill",
)
quiz_status = _enum("quiz_status", "pending", "active", "finished", "cancelled")
NEW_ENUMS = [review_due_reason, review_source, quiz_status]

TABLES = ["quiz", "quiz_item", "review_card", "review_log"]

KIND_LINKS_006 = (
    "(kind = 'kp') = (kp_id IS NOT NULL) AND (kind = 'remediation') = (remediation_id IS NOT NULL)"
    " AND (kind = 'practice') = (concept_id IS NOT NULL)"
)
KIND_LINKS_007 = (
    "(kind = 'kp') = (kp_id IS NOT NULL) AND (kind = 'remediation') = (remediation_id IS NOT NULL)"
    " AND (kind IN ('practice', 'review')) = (concept_id IS NOT NULL)"
    " AND (kind = 'quiz') = (quiz_id IS NOT NULL)"
)
SESSION_CHECK_006 = "(context IN ('kp', 'remediation', 'practice')) = (session_id IS NOT NULL)"
SESSION_CHECK_007 = (
    "(context IN ('kp', 'remediation', 'practice', 'review', 'quiz')) = (session_id IS NOT NULL)"
)

# The same scheduler as app/services/srs.py, duplicated so the migration doesn't import app code.
SCHEDULER = Scheduler(
    desired_retention=0.9, learning_steps=(), relearning_steps=(), enable_fuzzing=False
)


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _ts(name: str, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


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
    # New values can't be used in the transaction that adds them (the checks below use them).
    with op.get_context().autocommit_block():
        for enum_name in ("session_kind", "attempt_context", "xp_reason"):
            for value in ("review", "quiz"):
                op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")

    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind)

    op.create_table(
        "quiz",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("xp_mark", sa.Integer(), nullable=False),
        sa.Column("status", quiz_status, nullable=False),
        sa.Column("next_mark", sa.Integer(), nullable=True),
        _now("created_at"),
        _ts("started_at"),
        _ts("deadline"),
        _ts("finished_at"),
        sa.Column("correct", sa.SmallInteger(), nullable=True),
        sa.Column("total", sa.SmallInteger(), nullable=True),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quiz"),
        sa.UniqueConstraint("id", "org_id", name="uq_quiz_id_org_id"),
        sa.UniqueConstraint("student_id", "xp_mark", name="uq_quiz_student_id_xp_mark"),
        *_tenant("quiz"),
    )
    op.create_index("ix_quiz_org_id", "quiz", ["org_id"])
    op.create_index(
        "uq_quiz_open",
        "quiz",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'active')"),
    )

    op.create_table(
        "quiz_item",
        sa.Column("quiz_id", _uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("item_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("quiz_id", "position", name="pk_quiz_item"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            ondelete="RESTRICT",
            name="fk_quiz_item_org_id_organization",
        ),
        _tenant_fk("quiz_id", "quiz_item", "quiz"),
        _content_fk("quiz_item", "item_id", "item"),
        _content_fk("quiz_item", "concept_id", "concept"),
    )
    op.create_index("ix_quiz_item_org_id", "quiz_item", ["org_id"])

    op.create_table(
        "review_card",
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("stability", sa.Double(), nullable=False),
        sa.Column("difficulty", sa.Double(), nullable=False),
        _ts("due", nullable=False),
        _ts("last_review", nullable=False),
        sa.Column("reps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lapses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "consecutive_fails", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("credit", sa.Double(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "due_reason", review_due_reason, server_default=sa.text("'schedule'"), nullable=False
        ),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("student_id", "concept_id", name="pk_review_card"),
        sa.CheckConstraint("credit >= 0", name="ck_review_card_credit"),
        *_tenant("review_card"),
        _content_fk("review_card", "concept_id", "concept"),
    )
    op.create_index("ix_review_card_org_id", "review_card", ["org_id"])
    op.create_index(
        "ix_review_card_org_student_due", "review_card", ["org_id", "student_id", "due"]
    )

    op.create_table(
        "review_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("concept_id", _uuid(), nullable=False),
        sa.Column("source", review_source, nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("session_id", _uuid(), nullable=True),
        sa.Column("quiz_id", _uuid(), nullable=True),
        sa.Column("due_reason", review_due_reason, nullable=True),
        _ts("due_before"),
        _ts("due_after"),
        sa.Column("stability_before", sa.Double(), nullable=True),
        sa.Column("stability_after", sa.Double(), nullable=True),
        sa.Column("credit_added", sa.Numeric(), nullable=True),
        _now("created_at"),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_log"),
        *_tenant("review_log"),
        _tenant_fk("session_id", "review_log", "practice_session"),
        _tenant_fk("quiz_id", "review_log", "quiz"),
        _content_fk("review_log", "concept_id", "concept"),
    )
    op.create_index("ix_review_log_org_id", "review_log", ["org_id"])
    op.create_index(
        "ix_review_log_org_student_concept_created",
        "review_log",
        ["org_id", "student_id", "concept_id", "created_at"],
    )

    op.add_column("practice_session", sa.Column("quiz_id", _uuid(), nullable=True))
    op.create_foreign_key(
        "fk_practice_session_quiz_id_quiz",
        "practice_session",
        "quiz",
        ["quiz_id", "org_id"],
        ["id", "org_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_practice_session_kind_links", "practice_session", type_="check")
    op.create_check_constraint("ck_practice_session_kind_links", "practice_session", KIND_LINKS_007)
    op.create_index(
        "uq_practice_session_active_review",
        "practice_session",
        ["student_id", "concept_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND kind = 'review'"),
    )
    op.create_index(
        "uq_practice_session_quiz",
        "practice_session",
        ["quiz_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'quiz'"),
    )

    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.create_check_constraint("ck_attempt_session_iff_practice", "attempt", SESSION_CHECK_007)

    op.drop_index("uq_xp_event_session", table_name="xp_event")
    op.create_index(
        "uq_xp_event_session_subject",
        "xp_event",
        ["session_id", "subject"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    _backfill_cards()


def _backfill_cards() -> None:
    """A card per learned concept with gradable KP items, as if `learned_at` were a first Good."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT cs.org_id, cs.student_id, cs.concept_id, cs.learned_at
            FROM concept_state cs
            JOIN concept c ON c.id = cs.concept_id AND c.retired_at IS NULL
            WHERE cs.status = 'learned' AND cs.learned_at IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM item i
                JOIN knowledge_point kp ON kp.id = i.kp_id AND kp.retired_at IS NULL
                WHERE kp.concept_id = cs.concept_id AND i.retired_at IS NULL
                  AND i.kind = 'kp_question' AND i.type IN ('numeric', 'expression', 'mcq')
              )
            """
        )
    ).all()
    for org_id, student_id, concept_id, learned_at in rows:
        at = learned_at.astimezone(UTC)
        card, _ = SCHEDULER.review_card(Card(card_id=0), Rating.Good, at)
        params = {
            "org": org_id,
            "student": student_id,
            "concept": concept_id,
            "stability": card.stability,
            "difficulty": card.difficulty,
            "due": card.due,
            "last_review": at,
        }
        inserted = bind.execute(
            sa.text(
                """
                INSERT INTO review_card (org_id, student_id, concept_id, stability, difficulty,
                                         due, last_review, reps)
                VALUES (:org, :student, :concept, :stability, :difficulty, :due, :last_review, 1)
                ON CONFLICT DO NOTHING
                RETURNING concept_id
                """
            ),
            params,
        ).first()
        if inserted is None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO review_log (org_id, student_id, concept_id, source, rating,
                                        due_after, stability_after)
                VALUES (:org, :student, :concept, 'backfill', :rating, :due, :stability)
                """
            ),
            {**params, "rating": int(Rating.Good)},
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


def _session_kind_indexes() -> list[tuple[str, list[str], str]]:
    return [
        (
            "uq_practice_session_active_kp",
            ["student_id", "kp_id"],
            "status = 'active' AND kind = 'kp'",
        ),
        (
            "uq_practice_session_active_practice",
            ["student_id", "concept_id"],
            "status = 'active' AND kind = 'practice'",
        ),
    ]


def downgrade() -> None:
    # Review and quiz data can't be represented before 0008.
    op.execute("DELETE FROM xp_event WHERE reason IN ('review', 'quiz')")
    op.execute("DELETE FROM attempt WHERE context IN ('review', 'quiz')")
    op.execute("DELETE FROM review_log")
    op.execute("DELETE FROM practice_session WHERE kind IN ('review', 'quiz')")

    op.drop_index("uq_xp_event_session_subject", table_name="xp_event")
    op.create_index(
        "uq_xp_event_session",
        "xp_event",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    _shrink_enum("xp_reason", ["kp", "remediation", "practice"], "xp_event", "reason")

    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.drop_index("uq_attempt_learn_student_item", table_name="attempt")
    _shrink_enum(
        "attempt_context", ["learn", "kp", "remediation", "practice"], "attempt", "context"
    )
    op.create_index(
        "uq_attempt_learn_student_item",
        "attempt",
        ["student_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("context = 'learn'"),
    )
    op.create_check_constraint("ck_attempt_session_iff_practice", "attempt", SESSION_CHECK_006)

    op.drop_index("uq_practice_session_quiz", table_name="practice_session")
    op.drop_index("uq_practice_session_active_review", table_name="practice_session")
    for name, _cols, _where in _session_kind_indexes():
        op.drop_index(name, table_name="practice_session")
    op.drop_constraint("ck_practice_session_kind_links", "practice_session", type_="check")
    op.drop_constraint("fk_practice_session_quiz_id_quiz", "practice_session", type_="foreignkey")
    op.drop_column("practice_session", "quiz_id")
    _shrink_enum("session_kind", ["kp", "remediation", "practice"], "practice_session", "kind")
    op.create_check_constraint("ck_practice_session_kind_links", "practice_session", KIND_LINKS_006)
    for name, cols, where in _session_kind_indexes():
        op.create_index(
            name, "practice_session", cols, unique=True, postgresql_where=sa.text(where)
        )

    for table in ["review_log", "review_card", "quiz_item", "quiz"]:
        op.drop_table(table)
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind)
