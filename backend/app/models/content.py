"""Global content (spec 003): course → chapter → concept → knowledge_point → item; misconceptions.

Platform-owned and the same for every school: no `org_id`, no `TenantMixin`, never read through
`OrgScope` (RLS deny-all is still on). Rows are imported from `content/` by `app content import`:
the authored slug is the identity, `content_hash`/`version` track edits, and removed content is
retired (`retired_at`), never deleted.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenancy import Subject, _pg_enum


class Bloom(enum.StrEnum):
    remember = "remember"
    understand = "understand"
    apply = "apply"
    analyze = "analyze"
    evaluate = "evaluate"
    create = "create"


class ItemType(enum.StrEnum):
    numeric = "numeric"
    expression = "expression"
    mcq = "mcq"
    multistep = "multistep"
    code = "code"


class ItemKind(enum.StrEnum):
    kp_question = "kp_question"
    practice = "practice"
    misconception_check = "misconception_check"


class ContentMixin:
    """Identity (`slug`), edit tracking (`content_hash`, `version`) and retirement."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _fk(target: str) -> ForeignKey:
    return ForeignKey(target, ondelete="RESTRICT")


class Course(ContentMixin, Base):
    __tablename__ = "course"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_course_slug"),
        # At most one active course per subject (a class's course is found by its subject).
        Index(
            "uq_course_subject_active",
            "subject",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
        ),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Subject] = mapped_column(_pg_enum(Subject, "class_subject"), nullable=False)


class Chapter(ContentMixin, Base):
    __tablename__ = "chapter"
    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="uq_chapter_course_id_slug"),
        CheckConstraint("grade IN (9, 10)", name="grade"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("course.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)


class Concept(ContentMixin, Base):
    __tablename__ = "concept"
    __table_args__ = (UniqueConstraint("course_id", "slug", name="uq_concept_course_id_slug"),)

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("course.id"), nullable=False
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("chapter.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    intro_md: Mapped[str] = mapped_column(Text, nullable=False)


class ConceptPrereq(Base):
    """Prerequisite edge: `concept_id` requires `prereq_id`. Replaced to match files on import."""

    __tablename__ = "concept_prereq"
    __table_args__ = (
        CheckConstraint(
            "encompassing_weight > 0 AND encompassing_weight <= 1", name="weight_range"
        ),
        CheckConstraint("concept_id <> prereq_id", name="no_self_edge"),
    )

    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("concept.id"), primary_key=True
    )
    prereq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("concept.id"), primary_key=True, index=True
    )
    encompassing_weight: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)


class KnowledgePoint(ContentMixin, Base):
    __tablename__ = "knowledge_point"
    __table_args__ = (
        UniqueConstraint("concept_id", "slug", name="uq_knowledge_point_concept_id_slug"),
    )

    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("concept.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    worked_example_md: Mapped[str] = mapped_column(Text, nullable=False)


class KpKeyPrereq(Base):
    """A KP's key prerequisite concept (used for remediation after two fails)."""

    __tablename__ = "kp_key_prereq"

    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("knowledge_point.id"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("concept.id"), primary_key=True, index=True
    )


class Misconception(ContentMixin, Base):
    __tablename__ = "misconception"
    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="uq_misconception_course_id_slug"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("course.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class Item(ContentMixin, Base):
    """A question. `public` is all a client may ever see; `answer` never leaves the server."""

    __tablename__ = "item"
    __table_args__ = (
        UniqueConstraint("concept_id", "slug", name="uq_item_concept_id_slug"),
        CheckConstraint("(kp_id IS NOT NULL) = (kind = 'kp_question')", name="kp_iff_kp_question"),
    )

    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("concept.id"), nullable=False
    )
    kp_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _fk("knowledge_point.id"), index=True
    )
    kind: Mapped[ItemKind] = mapped_column(_pg_enum(ItemKind, "item_kind"), nullable=False)
    type: Mapped[ItemType] = mapped_column(_pg_enum(ItemType, "item_type"), nullable=False)
    bloom_level: Mapped[Bloom] = mapped_column(_pg_enum(Bloom, "bloom_level"), nullable=False)
    expected_minutes: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False)
    has_params: Mapped[bool] = mapped_column(Boolean, nullable=False)
    public: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
