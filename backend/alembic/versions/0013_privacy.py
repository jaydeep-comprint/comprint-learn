"""Privacy (spec 014): tutor consent, erasure, audit log.

- `user_status` + `erased`.
- `app_user`: tutor consent columns (students only), erasure request columns, `erased_at`.
- `audit_event` (append-only, RLS on, no policies).

Revision ID: 0013_privacy
Revises: 0012_placement
Create Date: 2026-11-11

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_privacy"
down_revision: str | Sequence[str] | None = "0012_placement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

audit_action = postgresql.ENUM(
    "consent_recorded",
    "consent_withdrawn",
    "export_downloaded",
    "erase_requested",
    "erase_cancelled",
    "erase_completed",
    "password_reset",
    "user_deactivated",
    "user_reactivated",
    name="audit_action",
    create_type=False,
)

# Copies of `app.models.tenancy.CONSENT_CHECK` / `ERASE_CHECK` as of this revision.
CONSENT_CHECK = (
    "(tutor_consent_at IS NULL AND tutor_consent_by IS NULL AND tutor_consent_form IS NULL)"
    " OR (tutor_consent_at IS NOT NULL AND tutor_consent_by IS NOT NULL"
    " AND tutor_consent_form IS NOT NULL AND role = 'student')"
)
ERASE_CHECK = (
    "(erase_requested_at IS NULL) = (erase_due_at IS NULL)"
    " AND (erase_requested_at IS NULL) = (erase_requested_by IS NULL)"
)
NEW_COLUMNS = (
    "tutor_consent_at",
    "tutor_consent_by",
    "tutor_consent_form",
    "erase_requested_at",
    "erase_requested_by",
    "erase_due_at",
    "erased_at",
)


def _uuid() -> postgresql.UUID[uuid.UUID]:
    return postgresql.UUID(as_uuid=True)


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _pair_fk(table: str, column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "org_id"], ["app_user.id", "app_user.org_id"], ondelete="RESTRICT", name=name
    )


def upgrade() -> None:
    # New values can't be used in the transaction that adds them (the check below uses it).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'erased'")

    op.add_column("app_user", _ts("tutor_consent_at"))
    op.add_column("app_user", sa.Column("tutor_consent_by", _uuid(), nullable=True))
    op.add_column("app_user", sa.Column("tutor_consent_form", sa.Text(), nullable=True))
    op.add_column("app_user", _ts("erase_requested_at"))
    op.add_column("app_user", sa.Column("erase_requested_by", _uuid(), nullable=True))
    op.add_column("app_user", _ts("erase_due_at"))
    op.add_column("app_user", _ts("erased_at"))
    for column in ("tutor_consent_by", "erase_requested_by"):
        op.create_foreign_key(
            f"fk_app_user_{column}_app_user",
            "app_user",
            "app_user",
            [column, "org_id"],
            ["id", "org_id"],
            ondelete="RESTRICT",
        )
    op.create_check_constraint("ck_app_user_tutor_consent", "app_user", CONSENT_CHECK)
    op.create_check_constraint("ck_app_user_erase_request", "app_user", ERASE_CHECK)
    op.create_check_constraint(
        "ck_app_user_erased_at", "app_user", "(status = 'erased') = (erased_at IS NOT NULL)"
    )
    op.create_index(
        "ix_app_user_erase_due_at",
        "app_user",
        ["erase_due_at"],
        postgresql_where=sa.text("erase_due_at IS NOT NULL"),
    )

    audit_action.create(op.get_bind())
    op.create_table(
        "audit_event",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=True),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("target_id", _uuid(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("org_id", _uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_event"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            ondelete="RESTRICT",
            name="fk_audit_event_org_id_organization",
        ),
        _pair_fk("audit_event", "actor_id", "fk_audit_event_actor_id_app_user"),
        _pair_fk("audit_event", "target_id", "fk_audit_event_target_id_app_user"),
    )
    op.create_index("ix_audit_event_org_id", "audit_event", ["org_id"])
    op.create_index(
        "ix_audit_event_org_created", "audit_event", ["org_id", sa.text("created_at DESC"), "id"]
    )
    op.create_index(
        "ix_audit_event_org_target", "audit_event", ["org_id", "target_id", "created_at"]
    )
    op.execute("ALTER TABLE public.audit_event ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("audit_event")
    audit_action.drop(op.get_bind())

    op.drop_index("ix_app_user_erase_due_at", table_name="app_user")
    for name in ("ck_app_user_erased_at", "ck_app_user_erase_request", "ck_app_user_tutor_consent"):
        op.drop_constraint(name, "app_user", type_="check")
    for column in ("tutor_consent_by", "erase_requested_by"):
        op.drop_constraint(f"fk_app_user_{column}_app_user", "app_user", type_="foreignkey")
    # Postgres can't drop an enum value: `erased` stays in `user_status`. Erased rows stay
    # anonymised (and banned in Supabase) as deactivated users.
    op.execute("UPDATE app_user SET status = 'deactivated' WHERE status = 'erased'")
    for column in NEW_COLUMNS:
        op.drop_column("app_user", column)
