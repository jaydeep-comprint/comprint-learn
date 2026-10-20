"""Real-database test: runs only under `make test-db` (pytest -m db) with TEST_DATABASE_URL set."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.main import create_app

pytestmark = pytest.mark.db


async def test_health_against_real_db(monkeypatch: pytest.MonkeyPatch) -> None:
    test_url = get_settings().test_database_url
    assert test_url
    monkeypatch.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()

    # Warm the pool first, as a running server always has: a cold TLS connect to the hosted
    # pooler can take longer than the health check's 3 s budget on its own. (Warming through the
    # endpoint doesn't work: its timeout cancels the connect, so nothing lands in the pool.)
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}
