from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.db.session import get_engine, get_session


async def test_engine_and_session_creation_open_no_connection() -> None:
    # conftest points DATABASE_URL at localhost with no server: connecting would raise.
    engine = get_engine()
    assert engine is get_engine()
    pool = engine.pool
    assert isinstance(pool, AsyncAdaptedQueuePool)
    assert pool.checkedout() == 0

    async for session in get_session():
        assert isinstance(session, AsyncSession)
    assert pool.checkedout() == 0
