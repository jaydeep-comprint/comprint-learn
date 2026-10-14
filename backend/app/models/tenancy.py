"""Tenancy: schools (organizations), users, classes, co-teachers and enrolments.

Every tenant-owned table inherits `TenantMixin` (`org_id`). Link tables also carry `org_id` with
composite foreign keys to `(id, org_id)` of both sides, so the database rejects cross-school links.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base

SCHOOL_CODE_PATTERN = r"^[A-Z0-9-]{3,12}$"


class Role(enum.StrEnum):
    teacher = "teacher"
    student = "student"


class UserStatus(enum.StrEnum):
    invited = "invited"
    active = "active"
    deactivated = "deactivated"


class Subject(enum.StrEnum):
    maths = "maths"
    physics = "physics"
    python = "python"


def _pg_enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class TenantMixin:
    """`org_id` NOT NULL, FK to organization, indexed. Query only through `OrgScope`."""

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 - SQLAlchemy declared_attr convention
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("organization.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = (
        CheckConstraint(f"code ~ '{SCHOOL_CODE_PATTERN}'", name="code_format"),
        UniqueConstraint("code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AppUser(TenantMixin, Base):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_app_user_id_org_id"),
        CheckConstraint("NOT is_admin OR role = 'teacher'", name="admin_is_teacher"),
        CheckConstraint(
            "(role = 'student') = (username IS NOT NULL AND email IS NULL)",
            name="student_identity",
        ),
        CheckConstraint("role = 'student' OR email IS NOT NULL", name="staff_email"),
        Index("uq_app_user_org_username", "org_id", text("lower(username)"), unique=True),
        Index("uq_app_user_email", text("lower(email)"), unique=True),
    )

    # Same as the Supabase auth user id (JWT `sub`).
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[Role] = mapped_column(_pg_enum(Role, "user_role"), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    status: Mapped[UserStatus] = mapped_column(_pg_enum(UserStatus, "user_status"), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SchoolClass(TenantMixin, Base):
    __tablename__ = "school_class"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_school_class_id_org_id"),
        CheckConstraint("grade IN (9, 10)", name="grade"),
        Index(
            "uq_school_class_org_name_active",
            "org_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        ForeignKeyConstraint(
            ["created_by", "org_id"],
            ["app_user.id", "app_user.org_id"],
            name="fk_school_class_created_by_app_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Subject] = mapped_column(_pg_enum(Subject, "class_subject"), nullable=False)
    grade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClassTeacher(TenantMixin, Base):
    """Links teachers to classes for the "My classes" view. Grants no extra access."""

    __tablename__ = "class_teacher"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "org_id"],
            ["school_class.id", "school_class.org_id"],
            ondelete="CASCADE",
            name="fk_class_teacher_class_school_class",
        ),
        ForeignKeyConstraint(
            ["user_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="CASCADE",
            name="fk_class_teacher_user_app_user",
        ),
    )

    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True)


class Enrollment(TenantMixin, Base):
    __tablename__ = "enrollment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "org_id"],
            ["school_class.id", "school_class.org_id"],
            ondelete="CASCADE",
            name="fk_enrollment_class_school_class",
        ),
        ForeignKeyConstraint(
            ["student_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="CASCADE",
            name="fk_enrollment_student_app_user",
        ),
    )

    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
