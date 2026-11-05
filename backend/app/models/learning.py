"""Learning state: attempts, lesson progress and study time (spec 004); concept states, KP progress,
practice sessions and remediations (spec 005); the XP ledger, day snapshots and own goals
(spec 008); review cards, the review log and quizzes (spec 007).

All tenant-owned (`TenantMixin`): the student link is a composite FK to `app_user(id, org_id)`, so a
row can't point at a student in another school. Content links (`item`, `concept`, `misconception`)
are plain FKs to the global content tables. Read and write only through `OrgScope`.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenancy import Subject, TenantMixin, _pg_enum


class AttemptContext(enum.StrEnum):
    """Where an answer was given. Later specs add diagnostic."""

    learn = "learn"
    kp = "kp"
    remediation = "remediation"
    practice = "practice"  # spec 006: the lesson's Practice step
    review = "review"  # spec 007: a scheduled (FSRS) review of one concept
    quiz = "quiz"  # spec 007: the mixed timed quiz


class StudyActivity(enum.StrEnum):
    learn = "learn"
    practice = "practice"


class ConceptStatus(enum.StrEnum):
    """Stored states only; `ready` / `locked` are computed (`app/services/frontier.py`)."""

    in_progress = "in_progress"
    learned = "learned"


class ConceptSource(enum.StrEnum):
    lesson = "lesson"
    diagnostic = "diagnostic"
    teacher = "teacher"


class KpStatus(enum.StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    passed = "passed"
    failed = "failed"


class SessionKind(enum.StrEnum):
    kp = "kp"
    remediation = "remediation"
    practice = "practice"  # spec 006: one practice item for a concept
    review = "review"  # spec 007: one review of a concept (`concept_id`)
    quiz = "quiz"  # spec 007: one quiz (`quiz_id`)


class SessionStatus(enum.StrEnum):
    active = "active"
    passed = "passed"
    failed = "failed"


class RemediationState(enum.StrEnum):
    review_due = "review_due"
    relearn = "relearn"
    resolved = "resolved"


class RemediationOutcome(enum.StrEnum):
    review_passed = "review_passed"
    relearned = "relearned"


def _student_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["student_id", "org_id"],
        ["app_user.id", "app_user.org_id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_student_app_user",
    )


def _content_fk(target: str) -> ForeignKey:
    return ForeignKey(target, ondelete="RESTRICT")


def _tenant_fk(column: str, table: str, target: str) -> ForeignKeyConstraint:
    """`(column, org_id)` → `target(id, org_id)`: a link can't cross schools."""
    return ForeignKeyConstraint(
        [column, "org_id"],
        [f"{target}.id", f"{target}.org_id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{column}_{target}",
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Attempt(TenantMixin, Base):
    """One answer submitted. Append-only; the Learn check allows one per student and item.

    KP, remediation and practice answers (specs 005, 006) belong to a `practice_session` at a
    `position`; a multi-step item stores one row per answered `step` (0 otherwise)."""

    __tablename__ = "attempt"
    __table_args__ = (
        _student_fk("attempt"),
        _tenant_fk("session_id", "attempt", "practice_session"),
        UniqueConstraint(
            "session_id", "position", "step", name="uq_attempt_session_id_position_step"
        ),
        CheckConstraint(
            "(context IN ('kp', 'remediation', 'practice', 'review', 'quiz')) = "
            "(session_id IS NOT NULL)",
            name="session_iff_practice",
        ),
        Index("ix_attempt_org_student_created", "org_id", "student_id", "created_at"),
        Index(
            "uq_attempt_learn_student_item",
            "student_id",
            "item_id",
            unique=True,
            postgresql_where=text("context = 'learn'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("item.id"), nullable=False
    )
    item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context: Mapped[AttemptContext] = mapped_column(
        _pg_enum(AttemptContext, "attempt_context"), nullable=False
    )
    seed: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correct: Mapped[bool] = mapped_column(nullable=False)
    misconception_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _content_fk("misconception.id")
    )
    time_taken_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    hints_used: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    position: Mapped[int | None] = mapped_column(SmallInteger)
    step: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LessonProgress(TenantMixin, Base):
    """Where a student is in a concept's lesson. `finished_at` is set once and never cleared."""

    __tablename__ = "lesson_progress"
    __table_args__ = (_student_fk("lesson_progress"),)

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), primary_key=True
    )
    seen_steps: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    last_step: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudyTime(TenantMixin, Base):
    """Active seconds on one lesson step (append-only). Ids and seconds only: no personal data."""

    __tablename__ = "study_time"
    __table_args__ = (
        _student_fk("study_time"),
        CheckConstraint("active_seconds BETWEEN 1 AND 600", name="active_seconds_range"),
        Index("ix_study_time_org_student_created", "org_id", "student_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), nullable=False
    )
    activity: Mapped[StudyActivity] = mapped_column(
        _pg_enum(StudyActivity, "study_activity"), nullable=False
    )
    step: Mapped[str] = mapped_column(Text, nullable=False)
    active_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConceptState(TenantMixin, Base):
    """A concept the student has started (`in_progress`) or `learned`; `ready`/`locked` are
    computed. Created on a lesson's first progress post; `learned` when every active KP is passed.
    A relearn (failed remediation review) sends it back to `in_progress`."""

    __tablename__ = "concept_state"
    __table_args__ = (_student_fk("concept_state"),)

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), primary_key=True
    )
    status: Mapped[ConceptStatus] = mapped_column(
        _pg_enum(ConceptStatus, "concept_status"), nullable=False
    )
    source: Mapped[ConceptSource] = mapped_column(
        _pg_enum(ConceptSource, "concept_source"), nullable=False
    )
    learned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    relearn_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class KpProgress(TenantMixin, Base):
    """Per student and KP: pass/fail state, fail count and the cooldown after a fail."""

    __tablename__ = "kp_progress"
    __table_args__ = (_student_fk("kp_progress"),)

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("knowledge_point.id"), primary_key=True
    )
    status: Mapped[KpStatus] = mapped_column(_pg_enum(KpStatus, "kp_status"), nullable=False)
    fail_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class Remediation(TenantMixin, Base):
    """Created by the 2nd (and later) fail of a KP, one per key prerequisite concept."""

    __tablename__ = "remediation"
    __table_args__ = (
        _student_fk("remediation"),
        UniqueConstraint("id", "org_id", name="uq_remediation_id_org_id"),
        Index(
            "uq_remediation_open",
            "student_id",
            "kp_id",
            "prereq_concept_id",
            unique=True,
            postgresql_where=text("state <> 'resolved'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("knowledge_point.id"), nullable=False
    )
    prereq_concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), nullable=False
    )
    state: Mapped[RemediationState] = mapped_column(
        _pg_enum(RemediationState, "remediation_state"), nullable=False
    )
    outcome: Mapped[RemediationOutcome | None] = mapped_column(
        _pg_enum(RemediationOutcome, "remediation_outcome")
    )
    created_at: Mapped[datetime] = _now()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PracticeSession(TenantMixin, Base):
    """One try at a KP's questions, one remediation review, one practice item for a concept
    (spec 006), one scheduled review of a concept or one quiz (spec 007).

    The question being shown (`current_*`) is stored before it is returned, so reloads and other
    tabs get the same item, seed and position."""

    __tablename__ = "practice_session"
    __table_args__ = (
        _student_fk("practice_session"),
        _tenant_fk("remediation_id", "practice_session", "remediation"),
        _tenant_fk("quiz_id", "practice_session", "quiz"),
        UniqueConstraint("id", "org_id", name="uq_practice_session_id_org_id"),
        CheckConstraint(
            "(kind = 'kp') = (kp_id IS NOT NULL) "
            "AND (kind = 'remediation') = (remediation_id IS NOT NULL) "
            "AND (kind IN ('practice', 'review')) = (concept_id IS NOT NULL) "
            "AND (kind = 'quiz') = (quiz_id IS NOT NULL)",
            name="kind_links",
        ),
        Index(
            "uq_practice_session_active_kp",
            "student_id",
            "kp_id",
            unique=True,
            postgresql_where=text("status = 'active' AND kind = 'kp'"),
        ),
        Index(
            "uq_practice_session_active_practice",
            "student_id",
            "concept_id",
            unique=True,
            postgresql_where=text("status = 'active' AND kind = 'practice'"),
        ),
        Index(
            "uq_practice_session_active_review",
            "student_id",
            "concept_id",
            unique=True,
            postgresql_where=text("status = 'active' AND kind = 'review'"),
        ),
        Index(
            "uq_practice_session_quiz",
            "quiz_id",
            unique=True,
            postgresql_where=text("kind = 'quiz'"),
        ),
        Index(
            "uq_practice_session_active_remediation",
            "remediation_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_practice_session_org_student_ended", "org_id", "student_id", "ended_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[SessionKind] = mapped_column(_pg_enum(SessionKind, "session_kind"), nullable=False)
    kp_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _content_fk("knowledge_point.id")
    )
    remediation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id")
    )
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[SessionStatus] = mapped_column(
        _pg_enum(SessionStatus, "session_status"), nullable=False
    )
    current_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _content_fk("item.id")
    )
    current_seed: Mapped[int | None] = mapped_column(Integer)
    current_position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    current_served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = _now()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class XpReason(enum.StrEnum):
    """What earned an `xp_event`; the values match `SessionKind` 1:1."""

    kp = "kp"
    remediation = "remediation"
    practice = "practice"
    review = "review"
    quiz = "quiz"


class XpGrade(enum.StrEnum):
    perfect = "perfect"
    passed = "passed"
    partial = "partial"
    poor = "poor"
    rushed = "rushed"


class XpEvent(TenantMixin, Base):
    """Append-only XP ledger (spec 008): one row per practice session ended by an answer (amount
    may be 0 or negative; a quiz writes one row per subject, spec 007), with the rule's inputs
    so an award can be audited and explained.
    Ids, numbers and the subject only: no personal data."""

    __tablename__ = "xp_event"
    __table_args__ = (
        _student_fk("xp_event"),
        _tenant_fk("session_id", "xp_event", "practice_session"),
        CheckConstraint("amount BETWEEN -100 AND 500", name="amount"),
        Index("ix_xp_event_org_student_day", "org_id", "student_id", "day"),
        Index(
            "uq_xp_event_session_subject",
            "session_id",
            "subject",
            unique=True,
            postgresql_where=text("session_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[XpReason] = mapped_column(_pg_enum(XpReason, "xp_reason"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), nullable=False
    )
    subject: Mapped[Subject] = mapped_column(_pg_enum(Subject, "class_subject"), nullable=False)
    amount: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    grade: Mapped[XpGrade] = mapped_column(_pg_enum(XpGrade, "xp_grade"), nullable=False)
    base_minutes: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    answered: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rushed_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hints: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = _now()


class XpDay(TenantMixin, Base):
    """Per student, IST date and subject: net XP (may be negative), the goal frozen at the day's
    first XP (raised, never lowered; null = no goal for that subject) and when it was met."""

    __tablename__ = "xp_day"
    __table_args__ = (
        _student_fk("xp_day"),
        CheckConstraint("goal BETWEEN 5 AND 60", name="goal"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    subject: Mapped[Subject] = mapped_column(_pg_enum(Subject, "class_subject"), primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    goal: Mapped[int | None] = mapped_column(SmallInteger)
    met_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class StudentGoal(TenantMixin, Base):
    """A student's own daily goal for a subject (at least the class goal when set)."""

    __tablename__ = "student_goal"
    __table_args__ = (
        _student_fk("student_goal"),
        CheckConstraint("goal BETWEEN 5 AND 60 AND goal % 5 = 0", name="goal"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    subject: Mapped[Subject] = mapped_column(_pg_enum(Subject, "class_subject"), primary_key=True)
    goal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    updated_at: Mapped[datetime] = _now()


class ReviewDueReason(enum.StrEnum):
    schedule = "schedule"
    quiz_miss = "quiz_miss"


class ReviewSource(enum.StrEnum):
    """What changed a review card (`review_log.source`)."""

    learned = "learned"
    relearned = "relearned"
    review = "review"
    brushup = "brushup"
    implicit = "implicit"
    quiz_miss = "quiz_miss"
    backfill = "backfill"


class QuizStatus(enum.StrEnum):
    pending = "pending"
    active = "active"
    finished = "finished"
    cancelled = "cancelled"


class ReviewCard(TenantMixin, Base):
    """FSRS state per student x concept (spec 007). The FSRS card is rebuilt from these columns
    and is always in the Review state (`app/services/srs.py`)."""

    __tablename__ = "review_card"
    __table_args__ = (
        _student_fk("review_card"),
        CheckConstraint("credit >= 0", name="credit"),
        Index("ix_review_card_org_student_due", "org_id", "student_id", "due"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), primary_key=True
    )
    stability: Mapped[float] = mapped_column(Double, nullable=False)
    difficulty: Mapped[float] = mapped_column(Double, nullable=False)
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_review: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    consecutive_fails: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    credit: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    due_reason: Mapped[ReviewDueReason] = mapped_column(
        _pg_enum(ReviewDueReason, "review_due_reason"),
        nullable=False,
        server_default=text("'schedule'"),
    )
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class ReviewLog(TenantMixin, Base):
    """Append-only: one row per change to a review card, with its cause (spec 007). Ids, numbers
    and dates only."""

    __tablename__ = "review_log"
    __table_args__ = (
        _student_fk("review_log"),
        _tenant_fk("session_id", "review_log", "practice_session"),
        _tenant_fk("quiz_id", "review_log", "quiz"),
        Index(
            "ix_review_log_org_student_concept_created",
            "org_id",
            "student_id",
            "concept_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), nullable=False
    )
    source: Mapped[ReviewSource] = mapped_column(
        _pg_enum(ReviewSource, "review_source"), nullable=False
    )
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    due_reason: Mapped[ReviewDueReason | None] = mapped_column(
        _pg_enum(ReviewDueReason, "review_due_reason")
    )
    due_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stability_before: Mapped[float | None] = mapped_column(Double)
    stability_after: Mapped[float | None] = mapped_column(Double)
    credit_added: Mapped[Decimal | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = _now()


class Quiz(TenantMixin, Base):
    """A mixed timed quiz, created at every ~150 lifetime XP (spec 007)."""

    __tablename__ = "quiz"
    __table_args__ = (
        _student_fk("quiz"),
        UniqueConstraint("id", "org_id", name="uq_quiz_id_org_id"),
        UniqueConstraint("student_id", "xp_mark", name="uq_quiz_student_id_xp_mark"),
        Index(
            "uq_quiz_open",
            "student_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'active')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    xp_mark: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[QuizStatus] = mapped_column(_pg_enum(QuizStatus, "quiz_status"), nullable=False)
    next_mark: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correct: Mapped[int | None] = mapped_column(SmallInteger)
    total: Mapped[int | None] = mapped_column(SmallInteger)


class QuizItem(TenantMixin, Base):
    """The questions of a quiz, chosen when it starts (positions 1 to N)."""

    __tablename__ = "quiz_item"
    __table_args__ = (_tenant_fk("quiz_id", "quiz_item", "quiz"),)

    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("item.id"), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _content_fk("concept.id"), nullable=False
    )
    seed: Mapped[int | None] = mapped_column(Integer)
