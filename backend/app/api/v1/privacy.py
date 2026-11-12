"""Spec 014: the consent notice (any signed-in user) and the audit log (admins)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminScope, Scope
from app.models import AuditAction
from app.privacy import notice
from app.schemas.privacy import AuditPage, NoticeOut
from app.services import audit

router = APIRouter(tags=["privacy"])


@router.get("/privacy/notice", response_model=NoticeOut)
async def get_notice(scope: Scope) -> NoticeOut:
    n = notice()
    return NoticeOut(version=n.version, title=n.title, body_md=n.body_md, stores_md=n.stores_md)


@router.get("/audit", response_model=AuditPage)
async def list_audit(
    scope: AdminScope,
    action: AuditAction | None = None,
    target_id: uuid.UUID | None = None,
    before: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=audit.MAX_PAGE)] = audit.DEFAULT_PAGE,
) -> AuditPage:
    return await audit.list_events(
        scope, action=action, target_id=target_id, before=before, limit=limit
    )
