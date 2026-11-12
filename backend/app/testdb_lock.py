"""One user of the shared test database at a time (spec 015).

`make test-db` and `make loadtest` both rebuild the one test Supabase project, so running them
together corrupts both. Each holds a session-level `pg_try_advisory_lock` on a dedicated
connection for its whole run; whoever comes second stops with `TestDbBusy`.
"""

import asyncpg

from app.core.config import normalize_db_url

# An arbitrary constant shared by the test suite and the load-test orchestrator.
LOCK_KEY = 15_015_015
BUSY_MESSAGE = (
    "The test database is in use by another `make test-db` or `make loadtest` run "
    "(one shared Supabase test project). Wait for it to finish, then try again."
)


class TestDbBusy(RuntimeError):  # noqa: N818 - a state, like `TutorUnavailable`
    __test__ = False  # not a pytest test class


def asyncpg_dsn(url: str) -> tuple[str, dict[str, object]]:
    sa_url, connect_args = normalize_db_url(url)
    return sa_url.replace("postgresql+asyncpg://", "postgresql://", 1), connect_args


async def acquire(url: str) -> asyncpg.Connection:
    """A connection holding the lock (close it to release). Raises `TestDbBusy`."""
    dsn, connect_args = asyncpg_dsn(url)
    conn: asyncpg.Connection = await asyncpg.connect(dsn, timeout=30, **connect_args)
    try:
        got = await conn.fetchval("select pg_try_advisory_lock($1)", LOCK_KEY)
    except BaseException:
        await conn.close()
        raise
    if not got:
        await conn.close()
        raise TestDbBusy(BUSY_MESSAGE)
    return conn
