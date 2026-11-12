"""Spec 015: request id, catch-all 500, access log (and, in PR 2, headers and the body cap)."""

import json
import logging
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.core.middleware import INTERNAL_MESSAGE, MAX_BODY_BYTES
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

    # Through an included router, as real routes are (FastAPI 0.143 nests them, so the route's
    # own `path` is relative to its router).
    from fastapi import APIRouter

    router = APIRouter()
    router.add_api_route("/students/{student_id}", student)
    app.include_router(router, prefix="/api/v1/_t")
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


def test_route_template_of_real_routes_keeps_the_prefix() -> None:
    from types import SimpleNamespace

    from app.core.middleware import route_template

    def tmpl(route_path: str, path: str) -> str:
        return route_template({"route": SimpleNamespace(path=route_path), "path": path})

    assert tmpl("/students/{student_id}", "/api/v1/students/abc") == (
        "/api/v1/students/{student_id}"
    )
    assert tmpl("/health", "/api/v1/health") == "/api/v1/health"
    assert (
        tmpl("/courses/{slug}/graph", "/api/v1/courses/m/graph") == "/api/v1/courses/{slug}/graph"
    )
    assert route_template({"path": "/x"}) == "(unmatched)"


# --- PR 2: security headers and the body cap ------------------------------------------------

BASE_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-resource-policy": "same-site",
}
JSON_CSP = "default-src 'none'; frame-ancestors 'none'"


@pytest.mark.parametrize("path", ["/api/v1/_t/ok", "/api/v1/_t/boom", "/api/v1/nope"])
async def test_security_headers_on_every_response(client: AsyncClient, path: str) -> None:
    resp = await client.get(path)
    for name, value in BASE_HEADERS.items():
        assert resp.headers[name] == value, name
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["content-security-policy"] == JSON_CSP
    assert "strict-transport-security" not in resp.headers


async def test_route_cache_control_is_kept_and_non_json_gets_no_csp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.responses import PlainTextResponse

    get_settings.cache_clear()
    app = create_app()

    async def text() -> PlainTextResponse:
        return PlainTextResponse("hi", headers={"Cache-Control": "private, max-age=60"})

    app.add_api_route("/api/v1/_t/text", text)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/_t/text")
    assert resp.headers["cache-control"] == "private, max-age=60"
    assert "content-security-policy" not in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_hsts_only_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_URL", "https://app.example.org")
    monkeypatch.setattr("app.main.configure_logging", lambda _s: None)
    get_settings.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        resp = await c.get("/api/v1/_t/ok")
    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def _echo_app() -> FastAPI:
    from pydantic import BaseModel

    class Code(BaseModel):
        code: str
        outputs: list[dict[str, str]]

    app = _app()

    async def submit(body: Code) -> dict[str, int]:
        return {"chars": len(body.code)}

    app.add_api_route("/api/v1/_t/submit", submit, methods=["POST"])
    return app


async def test_413_from_content_length() -> None:
    get_settings.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=_echo_app()), base_url="http://t") as c:
        resp = await c.post(
            "/api/v1/_t/submit",
            content=b"x" * (MAX_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 413
    assert resp.json() == {"code": "payload_too_large", "message": "That's too large to send."}
    assert resp.headers["x-request-id"]
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_413_for_an_oversized_chunked_body() -> None:
    get_settings.cache_clear()

    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"code": "'
        for _ in range(5):
            yield b"x" * 64 * 1024
        yield b'", "outputs": []}'

    async with AsyncClient(transport=ASGITransport(app=_echo_app()), base_url="http://t") as c:
        resp = await c.post(
            "/api/v1/_t/submit", content=chunks(), headers={"Content-Type": "application/json"}
        )
    assert "content-length" not in {k.lower() for k in resp.request.headers}
    assert resp.status_code == 413
    assert resp.json()["code"] == "payload_too_large"


async def test_a_maximal_code_submission_is_not_413() -> None:
    """20 000 chars of code (the grader's cap) plus realistic outputs for 30 tests."""
    get_settings.cache_clear()
    code = ("    x = some_function(a, b) + 1  # comment\n" * 500)[:20_000]
    outputs = [{"value": json.dumps([[i, i * 2.5, "some text"]] * 20)} for i in range(30)]
    async with AsyncClient(transport=ASGITransport(app=_echo_app()), base_url="http://t") as c:
        resp = await c.post("/api/v1/_t/submit", json={"code": code, "outputs": outputs})
    assert len(resp.request.content) < MAX_BODY_BYTES
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"chars": 20_000}
