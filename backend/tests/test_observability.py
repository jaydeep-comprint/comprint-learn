"""Spec 015: Sentry is off without a DSN, and `before_send` lets nothing personal through."""

import json
import logging
import sys
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError, field_validator

from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.core.observability import (
    JsonFormatter,
    before_breadcrumb,
    before_send,
    configure_logging,
    init_sentry,
)

NAME = "Asha Verma"
SECRET = "sk-live-0123456789abcdef"


def _hint(exc: BaseException) -> dict[str, Any]:
    return {"exc_info": (type(exc), exc, exc.__traceback__)}


def _event(value: str = "boom") -> dict[str, Any]:
    return {
        "message": value,
        "request": {
            "url": f"https://api.example.org/api/v1/students?q={NAME}",
            "method": "POST",
            "query_string": f"q={NAME}",
            "data": {"display_names": [NAME], "response": "42"},
            "cookies": {"sb": SECRET},
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Authorization": f"Bearer {SECRET}",
                "Cookie": f"sb={SECRET}",
                "X-Forwarded-For": "10.0.0.1",
            },
            "env": {"REMOTE_ADDR": "10.0.0.1"},
        },
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": value,
                    "stacktrace": {
                        "frames": [{"function": "f", "vars": {"name": NAME, "key": SECRET}}]
                    },
                }
            ]
        },
        "extra": {"display_name": NAME},
        "user": {"id": "u-1", "username": NAME, "email": "a@b.c", "ip_address": "10.0.0.1"},
        "breadcrumbs": {
            "values": [
                {
                    "category": "httplib",
                    "type": "http",
                    "data": {
                        "url": f"https://api.deepseek.com/chat/completions?key={SECRET}",
                        "method": "POST",
                        "status_code": 200,
                        "http.query": f"key={SECRET}",
                        "body": NAME,
                    },
                },
                {"category": "app", "message": "ok", "data": {"name": NAME}},
            ]
        },
    }


def test_no_dsn_never_initialises() -> None:
    get_settings.cache_clear()
    assert get_settings().sentry_dsn is None
    assert init_sentry(get_settings()) is False
    assert not sentry_sdk.get_client().is_active()


def test_empty_dsn_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")
    get_settings.cache_clear()
    assert get_settings().sentry_dsn is None


def test_before_send_strips_everything_personal() -> None:
    event = before_send(_event(), _hint(RuntimeError("boom")))
    assert event is not None
    req = event["request"]
    assert set(req) == {"url", "method", "headers"}
    assert req["url"] == "https://api.example.org/api/v1/students"
    assert req["headers"] == {"User-Agent": "Mozilla/5.0"}
    assert "vars" not in event["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "extra" not in event
    assert event["user"] == {"id": "u-1"}
    http, app_crumb = event["breadcrumbs"]["values"]
    assert http["data"] == {
        "url": "https://api.deepseek.com/chat/completions",
        "method": "POST",
        "status_code": 200,
    }
    assert "data" not in app_crumb
    dumped = json.dumps(event)
    assert NAME not in dumped and SECRET not in dumped and "10.0.0.1" not in dumped


def test_before_breadcrumb_scrubs_http_data() -> None:
    crumb = before_breadcrumb(
        {"category": "httplib", "data": {"url": f"https://x.org/a?t={SECRET}", "body": NAME}}, {}
    )
    assert crumb == {"category": "httplib", "data": {"url": "https://x.org/a"}}


class _Form(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _reject(cls, v: str) -> str:
        raise ValueError(f"bad value {v}")


def test_validation_error_carrying_a_name_and_secret_is_reduced_to_types() -> None:
    with pytest.raises(ValidationError) as info:
        _Form(name=f"{NAME} {SECRET}")
    exc = info.value
    event = before_send(_event(str(exc)), _hint(exc))
    assert event is not None
    value = event["exception"]["values"][0]["value"]
    assert value == "value_error at name"
    assert "message" not in event
    dumped = json.dumps(event)
    assert NAME not in dumped and SECRET not in dumped


def test_request_validation_error_is_reduced_to_types() -> None:
    exc = RequestValidationError(
        [{"type": "string_too_long", "loc": ("body", "note"), "msg": NAME, "input": SECRET}]
    )
    event = before_send(_event(str(exc)), _hint(exc))
    assert event is not None
    assert event["exception"]["values"][0]["value"] == "string_too_long at body.note"
    assert NAME not in json.dumps(event) and SECRET not in json.dumps(event)


def test_api_problem_below_500_is_dropped_and_5xx_kept() -> None:
    assert before_send(_event(), _hint(ApiProblem(404, "not_found"))) is None
    assert before_send(_event(), _hint(ApiProblem(429, "rate_limited"))) is None
    assert before_send(_event(), _hint(ApiProblem(503, "auth_unavailable"))) is not None


def test_api_problem_5xx_is_captured_with_a_code_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import _api_problem_handler

    calls: list[tuple[BaseException, list[str] | None]] = []

    def fake_capture(exc: BaseException, *, fingerprint: list[str] | None = None) -> None:
        calls.append((exc, fingerprint))

    monkeypatch.setattr("app.main.capture_exception", fake_capture)
    import asyncio

    problem = ApiProblem(503, "tutor_unavailable")
    asyncio.run(_api_problem_handler(None, problem))  # type: ignore[arg-type]
    asyncio.run(_api_problem_handler(None, ApiProblem(404, "not_found")))  # type: ignore[arg-type]
    assert calls == [(problem, ["api-problem", "tutor_unavailable"])]


def test_ai_errors_do_not_chain_the_provider_exception() -> None:
    import httpx

    from app.ai.client import TutorUnavailable

    def raise_like_client() -> None:
        try:
            raise httpx.ConnectError(f"https://api.deepseek.com/?key={SECRET}")
        except httpx.TransportError:
            raise TutorUnavailable("connection") from None

    with pytest.raises(TutorUnavailable) as info:
        raise_like_client()
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    access = logging.getLogger("uvicorn.access")
    saved_access = (access.handlers[:], access.propagate, access.disabled)
    yield
    root.handlers = saved[0]
    root.setLevel(saved[1])
    access.handlers, access.propagate, access.disabled = saved_access


def test_configure_logging_production_json(
    monkeypatch: pytest.MonkeyPatch, restore_logging: None
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    configure_logging(get_settings())
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").disabled


def test_configure_logging_development_untouched(restore_logging: None) -> None:
    before = logging.getLogger().handlers[:]
    get_settings.cache_clear()
    configure_logging(get_settings())
    assert logging.getLogger().handlers == before


def test_json_formatter_line() -> None:
    try:
        raise ValueError("x")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "hello %s", ("w",), exc_info)
    record.request_id = "r-1"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "hello w"
    assert line["level"] == "ERROR"
    assert line["logger"] == "app.x"
    assert line["request_id"] == "r-1"
    assert "ValueError" in line["exc"]


class _Capture(sentry_sdk.transport.Transport):
    def __init__(self, options: Any = None) -> None:
        super().__init__(options)
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sentry_capture(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Capture]:
    """Initialise Sentry for real (fake DSN) with a transport that keeps events in memory."""
    transport = _Capture()
    real_init = sentry_sdk.init

    def init(**kwargs: Any) -> Any:
        return real_init(transport=transport, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", init)
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.de.sentry.io/1")
    get_settings.cache_clear()
    yield transport
    sentry_sdk.flush(timeout=1)
    sentry_sdk.get_client().close(timeout=0)
    real_init(default_integrations=False)  # back to an inactive client


async def test_end_to_end_500_event_is_scrubbed(sentry_capture: _Capture) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app()

    async def boom(name: str) -> None:
        secret_local = f"{NAME} {SECRET}"  # noqa: F841 - must not appear as a local
        raise RuntimeError("kaboom")

    app.add_api_route("/api/v1/_t/boom", boom, methods=["POST"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            f"/api/v1/_t/boom?name={NAME}",
            json={"display_names": [NAME]},
            headers={"Authorization": f"Bearer {SECRET}", "X-Request-ID": "req-e2e-0001"},
            cookies={"sb": SECRET},
        )
    assert resp.status_code == 500
    sentry_sdk.flush()
    assert len(sentry_capture.events) == 1
    event = sentry_capture.events[0]
    assert event["tags"]["request_id"] == "req-e2e-0001"
    assert event["exception"]["values"][0]["value"] == "kaboom"
    assert event["exception"]["values"][0]["mechanism"]["type"] != "logging"
    dumped = json.dumps(event)
    assert NAME not in dumped and SECRET not in dumped
    assert "Asha" not in dumped


def _integrity_error() -> Exception:
    """What SQLAlchemy raises for an asyncpg unique violation: the DETAIL line echoes the row."""
    from sqlalchemy.exc import IntegrityError

    detail = "Key (org_id, lower(username))=(5f0c, asha.v) already exists."
    orig = Exception(
        f'duplicate key value violates unique constraint "uq_app_user_username"\nDETAIL:  {detail}'
    )
    try:
        raise IntegrityError("INSERT INTO app_user ...", None, orig)
    except IntegrityError as exc:
        return exc


def test_postgres_detail_never_reaches_sentry() -> None:
    exc = _integrity_error()
    assert "asha.v" in str(exc)  # the leak this guards against
    event = before_send(_event(str(exc)), _hint(exc))
    assert event is not None
    assert "asha.v" not in json.dumps(event)
    assert "uq_app_user_username" in event["exception"]["values"][0]["value"]


def test_postgres_detail_never_reaches_json_logs() -> None:
    exc = _integrity_error()
    record = logging.LogRecord(
        "app.x", logging.ERROR, __file__, 1, "failed: %s", (str(exc),), (type(exc), exc, None)
    )
    line = JsonFormatter().format(record)
    assert "asha.v" not in line
    assert "DETAIL: (removed)" in line


def test_multiline_postgres_detail_is_removed_entirely() -> None:
    from app.core.observability import scrub_text

    text = (
        'new row violates check constraint "ck_attempt"\n'
        'DETAIL:  Failing row contains (1, def f():\n    return "Asha Verma", 2).\n'
        "[SQL: INSERT INTO attempt ...]\n"
        "(Background on this error at: https://sqlalche.me/e/21/gkpj)"
    )
    out = scrub_text(text)
    assert "Asha" not in out and "return" not in out
    assert out.startswith('new row violates check constraint "ck_attempt"\nDETAIL: (removed)\n')
    assert "[SQL: INSERT INTO attempt ...]" in out
    # DETAIL as the last section (asyncpg's own str()).
    assert scrub_text("dup key\nDETAIL:  Key (username)=(asha\nv) exists.") == (
        "dup key\nDETAIL: (removed)\n"
    )
