"""Audit log (spec 014): append-only `audit_event` rows, written in the caller's transaction.

`meta` holds counts and versions only, never names, usernames, emails or free text.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import tuple_
from sqlalchemy.orm import aliased

from app.api.deps import SYSTEM_ACTOR_ID, OrgScope
from app.core.errors import ApiProblem
from app.models import AppUser, AuditAction, AuditEvent
from app.schemas.privacy import AuditEventOut, AuditPage, AuditUser

MAX_PAGE = 100
DEFAULT_PAGE = 50

_ACTOR_FROM_SCOPE: Any = object()
_META_TYPES = (int, float, bool, str, type(None))


def record(
    scope: OrgScope,
    action: AuditAction,
    target_id: uuid.UUID | None,
    meta: dict[str, Any] | None = None,
    *,
    actor_id: uuid.UUID | None = _ACTOR_FROM_SCOPE,
) -> None:
    """Adds one event to the session; the caller's commit writes it with the change it records.
    The actor defaults to the signed-in user; the CLI and jobs pass `actor_id=None` (System)."""
    actor = scope.user.id if actor_id is _ACTOR_FROM_SCOPE else actor_id
    if actor == SYSTEM_ACTOR_ID:
        raise ValueError("system scope: pass actor_id=None")
    meta = meta or {}
    if not all(isinstance(v, _META_TYPES) for v in meta.values()):
        raise ValueError("audit meta holds scalars only")
    scope.new(AuditEvent, actor_id=actor, action=action, target_id=target_id, meta=meta)


def _cursor(at: datetime, id_: uuid.UUID) -> str:
    return f"{at.isoformat()}_{id_}"


def _parse_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, id_ = raw.rsplit("_", 1)
        return datetime.fromisoformat(at), uuid.UUID(id_)
    except ValueError as exc:
        raise ApiProblem(422, "bad_cursor", "That page link is not valid.") from exc


async def list_events(
    scope: OrgScope,
    *,
    action: AuditAction | None = None,
    target_id: uuid.UUID | None = None,
    before: str | None = None,
    limit: int = DEFAULT_PAGE,
) -> AuditPage:
    """Newest first, keyset-paginated on `(created_at, id)` (events of one request share a
    `created_at`)."""
    limit = max(1, min(limit, MAX_PAGE))
    actor = aliased(AppUser)
    target = aliased(AppUser)
    stmt = (
        scope.select(AuditEvent)
        .add_columns(actor.id, actor.display_name, target.id, target.display_name)
        .outerjoin(actor, (actor.id == AuditEvent.actor_id) & (actor.org_id == AuditEvent.org_id))
        .outerjoin(
            target, (target.id == AuditEvent.target_id) & (target.org_id == AuditEvent.org_id)
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit + 1)
    )
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if target_id is not None:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    if before:
        at, id_ = _parse_cursor(before)
        stmt = stmt.where(tuple_(AuditEvent.created_at, AuditEvent.id) < tuple_(at, id_))
    rows = (await scope.session.execute(stmt)).all()
    items = [
        AuditEventOut(
            id=ev.id,
            action=ev.action,
            at=ev.created_at,
            actor=AuditUser(id=a_id, display_name=a_name) if a_id else None,
            target=AuditUser(id=t_id, display_name=t_name) if t_id else None,
            meta=ev.meta,
        )
        for ev, a_id, a_name, t_id, t_name in rows[:limit]
    ]
    last = rows[limit - 1][0] if len(rows) > limit else None
    return AuditPage(items=items, next_before=_cursor(last.created_at, last.id) if last else None)
