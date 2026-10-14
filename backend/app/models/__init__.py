"""All models are imported here so `Base.metadata` (and Alembic) sees every table."""

from app.models.tenancy import (
    AppUser,
    ClassTeacher,
    Enrollment,
    Organization,
    Role,
    SchoolClass,
    Subject,
    TenantMixin,
    UserStatus,
)

__all__ = [
    "AppUser",
    "ClassTeacher",
    "Enrollment",
    "Organization",
    "Role",
    "SchoolClass",
    "Subject",
    "TenantMixin",
    "UserStatus",
]
