"""Auth & tenancy: organization, app_user, school_class, class_teacher, enrollment; RLS deny-all.

Revision ID: 0002_auth_tenancy
Revises: 0001_baseline
Create Date: 2026-10-14

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_auth_tenancy"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("teacher", "student", name="user_role", create_type=False)
user_status = postgresql.ENUM(
    "invited", "active", "deactivated", name="user_status", create_type=False
)
class_subject = postgresql.ENUM("maths", "physics", "python", name="class_subject", create_type=False)

# Deny-all for Supabase's Data API (anon / authenticated keys): RLS on, no policies, on every table
# in `public`. The backend connects as `postgres`, which bypasses RLS. Later migrations that add
# tables must run this same statement again (tests/test_rls_db.py catches a miss).
ENABLE_RLS_ON_ALL_PUBLIC_TABLES = """
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;
"""


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["org_id"],
        ["organization.id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_org_id_organization",
    )


def upgrade() -> None:
    bind = op.get_bind()
    user_role.create(bind)
    user_status.create(bind)
    class_subject.create(bind)

    op.create_table(
        "organization",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization"),
        sa.UniqueConstraint("code", name="uq_organization_code"),
        sa.CheckConstraint("code ~ '^[A-Z0-9-]{3,12}$'", name="ck_organization_code_format"),
    )

    op.create_table(
        "app_user",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("status", user_status, nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("sessions_valid_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.UniqueConstraint("id", "org_id", name="uq_app_user_id_org_id"),
        sa.CheckConstraint("NOT is_admin OR role = 'teacher'", name="ck_app_user_admin_is_teacher"),
        sa.CheckConstraint(
            "(role = 'student') = (username IS NOT NULL AND email IS NULL)",
            name="ck_app_user_student_identity",
        ),
        sa.CheckConstraint(
            "role = 'student' OR email IS NOT NULL", name="ck_app_user_staff_email"
        ),
        _org_fk("app_user"),
    )
    op.create_index("ix_app_user_org_id", "app_user", ["org_id"])
    op.create_index(
        "uq_app_user_org_username", "app_user", ["org_id", sa.text("lower(username)")], unique=True
    )
    op.create_index("uq_app_user_email", "app_user", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "school_class",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subject", class_subject, nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", _uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_school_class"),
        sa.UniqueConstraint("id", "org_id", name="uq_school_class_id_org_id"),
        sa.CheckConstraint("grade IN (9, 10)", name="ck_school_class_grade"),
        sa.ForeignKeyConstraint(
            ["created_by", "org_id"],
            ["app_user.id", "app_user.org_id"],
            name="fk_school_class_created_by_app_user",
        ),
        _org_fk("school_class"),
    )
    op.create_index("ix_school_class_org_id", "school_class", ["org_id"])
    op.create_index(
        "uq_school_class_org_name_active",
        "school_class",
        ["org_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "class_teacher",
        sa.Column("class_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("class_id", "user_id", name="pk_class_teacher"),
        sa.ForeignKeyConstraint(
            ["class_id", "org_id"],
            ["school_class.id", "school_class.org_id"],
            ondelete="CASCADE",
            name="fk_class_teacher_class_school_class",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="CASCADE",
            name="fk_class_teacher_user_app_user",
        ),
        _org_fk("class_teacher"),
    )
    op.create_index("ix_class_teacher_org_id", "class_teacher", ["org_id"])
    op.create_index("ix_class_teacher_user_id", "class_teacher", ["user_id"])

    op.create_table(
        "enrollment",
        sa.Column("class_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("class_id", "student_id", name="pk_enrollment"),
        sa.ForeignKeyConstraint(
            ["class_id", "org_id"],
            ["school_class.id", "school_class.org_id"],
            ondelete="CASCADE",
            name="fk_enrollment_class_school_class",
        ),
        sa.ForeignKeyConstraint(
            ["student_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="CASCADE",
            name="fk_enrollment_student_app_user",
        ),
        _org_fk("enrollment"),
    )
    op.create_index("ix_enrollment_org_id", "enrollment", ["org_id"])
    op.create_index("ix_enrollment_student_id", "enrollment", ["student_id"])

    op.execute(ENABLE_RLS_ON_ALL_PUBLIC_TABLES)


def downgrade() -> None:
    op.drop_table("enrollment")
    op.drop_table("class_teacher")
    op.drop_table("school_class")
    op.drop_table("app_user")
    op.drop_table("organization")
    bind = op.get_bind()
    class_subject.drop(bind)
    user_status.drop(bind)
    user_role.drop(bind)
