"""Spec 015: request id, catch-all 500, access log (and, in PR 2, headers and the body cap)."""

import json
import logging
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.core.middleware import INTERNAL_MESSAGE
from app.core.observability import JsonFormatter, RequestIdFilter
from app.main import create_app

ORIGIN = "https://app.example.org"


def _app() -> FastAPI:
    app = create_app()

    async def ok() -> dict[str, str]:
        return {"ok": "yes"}

    async def boom() -> None:
        raise RuntimeError("secret detail: Asha Verma's answer was 42")

    async def problem() -> None:
        raise ApiProblem(429, "rate_limited", "Slow down.", headers={"Retry-After": "7"})

    app.add_api_route("/api/v1/_t/ok", ok)
    app.add_api_route("/api/v1/_t/boom", boom)
    app.add_api_route("/api/v1/_t/problem", problem)
    return app


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("CORS_ORIGINS", ORIGIN)
    get_settings.cache_clear()
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_request_id_generated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/_t/ok")
    rid = resp.headers["x-request-id"]
    assert len(rid) == 32 and rid.isalnum()


async def test_request_id_accepted_when_well_formed(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/_t/ok", headers={"X-Request-ID": "abc-12345-XYZ"})
    assert resp.headers["x-request-id"] == "abc-12345-XYZ"


@pytest.mark.parametrize("bad", ["short", "has space in it", "x" * 65, "semi;colon123"])
async def test_request_id_replaced_when_malformed(client: AsyncClient, bad: str) -> None:
    resp = await client.get("/api/v1/_t/ok", headers={"X-Request-ID": bad})
    assert resp.headers["x-request-id"] != bad
    assert len(resp.headers["x-request-id"]) == 32


async def test_request_id_on_unmatched_routes(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.headers["x-request-id"]


async def test_catch_all_500_shape(client: AsyncClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="app.core.middleware"):
        resp = await client.get(
            "/api/v1/_t/boom", headers={"Origin": ORIGIN, "X-Request-ID": "req-00000001"}
        )
    assert resp.status_code == 500
    assert resp.json() == {
        "code": "internal",
        "message": INTERNAL_MESSAGE,
        "request_id": "req-00000001",
    }
    assert "Traceback" not in resp.text and "secret detail" not in resp.text
    # Still inside CORS and the request id middleware.
    assert resp.headers["access-control-allow-origin"] == ORIGIN
    assert "X-Request-ID" in resp.headers["access-control-expose-headers"]
    assert resp.headers["x-request-id"] == "req-00000001"
    # Logged with the exception for the developer.
    assert "unhandled error on GET /api/v1/_t/boom" in caplog.text


async def test_api_problem_headers_pass_through(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/_t/problem", headers={"Origin": ORIGIN})
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "7"
    assert resp.json() == {"code": "rate_limited", "message": "Slow down."}
    assert "Retry-After" in resp.headers["access-control-expose-headers"]


async def test_production_access_log_uses_route_template(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_URL", "https://app.example.org")
    # Keep pytest's log capture: configure_logging (tested in test_observability) swaps handlers.
    monkeypatch.setattr("app.main.configure_logging", lambda _s: None)
    get_settings.cache_clear()
    app = create_app()

    async def student(student_id: str) -> dict[str, str]:
        return {"id": student_id}

    app.add_api_route("/api/v1/_t/students/{student_id}", student)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with caplog.at_level(logging.INFO, logger="app.access"):
            await c.get("/api/v1/_t/students/abc?name=Asha", headers={"X-Request-ID": "r-123456"})
            await c.get("/api/v1/zzz")
    records = [r for r in caplog.records if r.name == "app.access"]
    assert [getattr(r, "path") for r in records] == [  # noqa: B009
        "/api/v1/_t/students/{student_id}",
        "(unmatched)",
    ]
    first = records[0]
    assert getattr(first, "status") == 200  # noqa: B009
    assert getattr(first, "method") == "GET"  # noqa: B009
    RequestIdFilter().filter(first)
    line = json.loads(JsonFormatter().format(first))
    assert line["path"] == "/api/v1/_t/students/{student_id}"
    assert line["request_id"] == "r-123456"
    assert {"ts", "level", "logger", "msg", "ms", "user_id", "org_id"} <= line.keys()
    assert "Asha" not in json.dumps(line)


async def test_no_access_log_in_development(caplog: pytest.LogCaptureFixture) -> None:
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with caplog.at_level(logging.INFO, logger="app.access"):
            await c.get("/api/v1/zzz")
    assert not [r for r in caplog.records if r.name == "app.access"]
