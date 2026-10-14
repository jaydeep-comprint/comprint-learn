"""Real-database test: runs only under `make test-db` (pytest -m db) with TEST_DATABASE_URL set."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app

pytestmark = pytest.mark.db


async def test_health_against_real_db(monkeypatch: pytest.MonkeyPatch) -> None:
    test_url = get_settings().test_database_url
    assert test_url
    monkeypatch.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}
