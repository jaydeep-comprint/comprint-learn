"""Spec 014: notice, consent, audit log, erasure."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import AuditAction

MAX_CONSENT_IDS = 200


class NoticeOut(BaseModel):
    version: str
    title: str
    body_md: str
    stores_md: str


class ConsentIn(BaseModel):
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_CONSENT_IDS)
    action: Literal["record", "withdraw"]


class AuditUser(BaseModel):
    id: uuid.UUID
    display_name: str


class AuditEventOut(BaseModel):
    id: uuid.UUID
    action: AuditAction
    at: datetime
    actor: AuditUser | None  # null = the system (CLI or scheduled job)
    target: AuditUser | None
    meta: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    next_before: str | None  # opaque cursor for the next (older) page; null on the last page


class EraseIn(BaseModel):
    confirm_username: str = Field(max_length=100)
