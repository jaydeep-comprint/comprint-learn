"""Learning state (spec 004): check attempts, lesson progress, and study time per student.

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenancy import TenantMixin, _pg_enum


class AttemptContext(enum.StrEnum):
    """Where an answer was given. Later specs add practice, review, quiz, diagnostic."""

    learn = "learn"


class StudyActivity(enum.StrEnum):
    learn = "learn"


def _student_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["student_id", "org_id"],
        ["app_user.id", "app_user.org_id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_student_app_user",
    )


def _content_fk(target: str) -> ForeignKey:
    return ForeignKey(target, ondelete="RESTRICT")


class Attempt(TenantMixin, Base):
    """One answer submitted. Append-only; the Learn check allows one per student and item."""

    __tablename__ = "attempt"
    __table_args__ = (
        _student_fk("attempt"),
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
