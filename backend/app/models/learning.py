"""Learning state: attempts, lesson progress and study time (spec 004); concept states, KP progress,
practice sessions and remediations (spec 005).

All tenant-owned (`TenantMixin`): the student link is a composite FK to `app_user(id, org_id)`, so a
row can't point at a student in another school. Content links (`item`, `concept`, `misconception`)
are plain FKs to the global content tables. Read and write only through `OrgScope`.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenancy import TenantMixin, _pg_enum


class AttemptContext(enum.StrEnum):
    """Where an answer was given. Later specs add review, quiz, diagnostic."""

    learn = "learn"
    kp = "kp"
    remediation = "remediation"
    practice = "practice"  # spec 006: the lesson's Practice step


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
            "(context IN ('kp', 'remediation', 'practice')) = (session_id IS NOT NULL)",
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
    """One try at a KP's questions, one remediation review, or one practice item for a concept
    (spec 006; 007 may reuse it for reviews).

    The question being shown (`current_*`) is stored before it is returned, so reloads and other
    tabs get the same item, seed and position."""

    __tablename__ = "practice_session"
    __table_args__ = (
        _student_fk("practice_session"),
        _tenant_fk("remediation_id", "practice_session", "remediation"),
        UniqueConstraint("id", "org_id", name="uq_practice_session_id_org_id"),
        CheckConstraint(
            "(kind = 'kp') = (kp_id IS NOT NULL) "
            "AND (kind = 'remediation') = (remediation_id IS NOT NULL) "
            "AND (kind = 'practice') = (concept_id IS NOT NULL)",
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
