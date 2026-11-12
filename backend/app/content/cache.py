"""A per-process cache of global content (spec 015 load test; decided by the user, Nov 2026).

Courses, chapters, concepts, prerequisite edges, knowledge points and items are platform-owned and
change only on `app content import` (or a DB test's truncate and re-import). Every learn and
dashboard request used to reload them: 8-13 of its 21-38 queries. Now each session runs one small
`stamp` query (row counts and the latest `updated_at` of each content table) and reuses what was
loaded for the same stamp. Nothing tenant-owned or student-specific is cached.

Cached values must be treated as read-only: callers that need mutable objects build fresh ones
from them (see `frontier.active_kps`).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_TABLES = ("course", "chapter", "concept", "knowledge_point", "item", "misconception")
_EDGES = ("concept_prereq", "kp_key_prereq")
STAMP_SQL = text(
    "SELECT "
    + ", ".join(
        [
            f"(SELECT max(updated_at) FROM {t}), "
            f"(SELECT count(*) FROM {t} WHERE retired_at IS NULL)"
            for t in _TABLES
        ]
        + [f"(SELECT count(*) FROM {t})" for t in _EDGES]
    )
)
_STAMP_KEY = "content_stamp"

type Stamp = tuple[Any, ...]

_cache: dict[str, tuple[Stamp, Any]] = {}


async def stamp(session: AsyncSession) -> Stamp:
    """The content tables' stamp, once per transaction."""
    info = session.sync_session.info
    found: Stamp | None = info.get(_STAMP_KEY)
    if found is None:
        found = tuple((await session.execute(STAMP_SQL)).one())
        info[_STAMP_KEY] = found
    return found


async def cached[T](session: AsyncSession, name: str, load: Callable[[], Awaitable[T]]) -> T:
    """`load()`'s value for the current content, loaded at most once per content change."""
    current = await stamp(session)
    hit = _cache.get(name)
    if hit is not None and hit[0] == current:
        value: T = hit[1]
        return value
    value = await load()
    _cache[name] = (current, value)
    return value


def clear() -> None:
    _cache.clear()


@event.listens_for(Session, "after_transaction_end")
def _forget_stamp(session: Session, _transaction: Any) -> None:
    # A new transaction may see an import committed meanwhile: check the stamp again.
    session.info.pop(_STAMP_KEY, None)
