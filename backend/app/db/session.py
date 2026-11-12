"""Async engine and sessions. The engine is created lazily; creating it opens no connection."""

import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.observability import query_stats_var

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url, connect_args = settings.db_connection()
        _engine = create_async_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            # Error messages and logs never include bound values (names, emails).
            hide_parameters=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        _count_queries(_engine)
    return _engine


def _count_queries(engine: AsyncEngine) -> None:
    """Statements and their time per request, for the access log (ids and counts only)."""

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before(conn: Any, _cursor: Any, _stmt: Any, _params: Any, _ctx: Any, _many: Any) -> None:
        conn.info["query_started"] = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after(conn: Any, _cursor: Any, _stmt: Any, _params: Any, _ctx: Any, _many: Any) -> None:
        stats = query_stats_var.get()
        if stats is not None:
            stats[0] += 1
            stats[1] += (
                time.perf_counter() - conn.info.pop("query_started", time.perf_counter())
            ) * 1000


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one `AsyncSession` per request."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
