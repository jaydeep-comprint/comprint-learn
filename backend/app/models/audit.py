"""Audit log (spec 014): one append-only row per privacy or account action.

No names, usernames, emails or free text are stored: only ids, the action and a small `meta` of
counts/versions. A null `actor_id` is the system (the CLI or the scheduled job).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenancy import TenantMixin, _pg_enum


class AuditAction(enum.StrEnum):
    consent_recorded = "consent_recorded"
    consent_withdrawn = "consent_withdrawn"
    export_downloaded = "export_downloaded"
    erase_requested = "erase_requested"
    erase_cancelled = "erase_cancelled"
    erase_completed = "erase_completed"
    password_reset = "password_reset"
    user_deactivated = "user_deactivated"
    user_reactivated = "user_reactivated"


class AuditEvent(TenantMixin, Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="RESTRICT",
            name="fk_audit_event_actor_id_app_user",
        ),
        ForeignKeyConstraint(
            ["target_id", "org_id"],
            ["app_user.id", "app_user.org_id"],
            ondelete="RESTRICT",
            name="fk_audit_event_target_id_app_user",
        ),
        Index("ix_audit_event_org_created", "org_id", text("created_at DESC"), "id"),
        Index("ix_audit_event_org_target", "org_id", "target_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[AuditAction] = mapped_column(
        _pg_enum(AuditAction, "audit_action"), nullable=False
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
