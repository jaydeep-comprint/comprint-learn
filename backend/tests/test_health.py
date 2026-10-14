import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import health
from app.db.session import get_session
from app.main import create_app, lifespan

SECRET = "password authentication failed for user postgres at db.secret-host:5432"


class FakeSession:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    async def execute(self, _stmt: Any) -> None:
        if self.behaviour == "raise":
            raise ConnectionRefusedError(SECRET)
        if self.behaviour == "hang":
            await asyncio.sleep(10)


def app_with_session(behaviour: str) -> FastAPI:
    app = create_app()

    async def fake_session() -> AsyncIterator[FakeSession]:
        yield FakeSession(behaviour)

    app.dependency_overrides[get_session] = fake_session
    return app


async def get_health(app: FastAPI) -> tuple[int, Any, str]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    return resp.status_code, resp.json(), resp.text


async def test_health_ok() -> None:
    status, body, _ = await get_health(app_with_session("ok"))
    assert status == 200
    assert body == {"status": "ok", "db": "ok"}


async def test_health_db_error_is_503_without_leaking(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.api.v1.health"):
        status, body, text = await get_health(app_with_session("raise"))
    assert status == 503
    assert body == {"status": "error", "db": "error"}
    assert "secret-host" not in text
    assert "ConnectionRefusedError" in caplog.text
    assert "secret-host" not in caplog.text


async def test_health_db_timeout_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "HEALTH_DB_TIMEOUT_S", 0.05)
    status, body, _ = await get_health(app_with_session("hang"))
    assert status == 503
    assert body == {"status": "error", "db": "error"}


async def test_transaction_pooler_port_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@aws-0-x.pooler.supabase.com:6543/postgres")
    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with lifespan(FastAPI()):
            pass
    assert "Session pooler, port 5432" in caplog.text
