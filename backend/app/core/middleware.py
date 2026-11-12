"""Pure ASGI middleware (spec 015), not `BaseHTTPMiddleware`, so streaming and cancellation work.

Order, outermost first (see `app.main.create_app`):
request id → CORS → security headers → body cap → catch-all → app.

- `RequestIdMiddleware`: every request gets an id (a well-formed incoming `X-Request-ID`, else a
  new uuid4 hex), returned as `X-Request-ID`, kept in a contextvar for logs and Sentry, and in
  production one access log line per request (route template, never the raw URL).
- `CatchAllMiddleware`: an unhandled exception becomes `500 {"code": "internal", ...}` with the
  request id, never a stack trace; reported to Sentry and logged. It sits inside CORS, so the 500
  still carries the CORS headers (an `add_exception_handler(Exception)` would run outside them).
- `SecurityHeadersMiddleware`: nosniff, no-referrer, DENY framing, CORP, `no-store` on `/api/*`, a
  deny-all CSP on JSON responses and HSTS in production.
- `BodyCapMiddleware`: bodies over 256 KB → 413 `payload_too_large`, from `Content-Length` and
  while reading chunked bodies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any

import sentry_sdk
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.observability import (
    ACCESS_LOGGER,
    capture_exception,
    query_stats_var,
    request_id_var,
)

log = logging.getLogger(__name__)
access_log = logging.getLogger(ACCESS_LOGGER)

REQUEST_ID_HEADER = b"x-request-id"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
INTERNAL_MESSAGE = "Something went wrong. Please try again."


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == REQUEST_ID_HEADER:
            try:
                text = value.decode("latin-1")
            except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes any bytes
                return None
            return text if _VALID_REQUEST_ID.fullmatch(text) else None
    return None


def _state(scope: Scope) -> dict[str, Any]:
    state: dict[str, Any] = scope.setdefault("state", {})
    return state


def route_template(scope: Scope) -> str:
    """The matched route's full path template (`/api/v1/students/{student_id}`), else
    "(unmatched)". FastAPI 0.143 nests included routers, so `route.path` is relative to its
    router (`/students/{student_id}`): the prefix is the request path minus as many trailing
    segments as the template has (no route uses a `{x:path}` parameter)."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if not isinstance(template, str):
        return "(unmatched)"
    path = str(scope.get("path") or "")
    depth = template.rstrip("/").count("/")
    segments = path.rstrip("/").split("/")
    if depth and len(segments) > depth:
        prefix = "/".join(segments[:-depth])
        return f"{prefix}{template}"
    return template


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp, *, access_log_enabled: bool = False) -> None:
        self.app = app
        self.access_log_enabled = access_log_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        _state(scope)["request_id"] = request_id
        token = request_id_var.set(request_id)
        stats: list[float] = [0, 0.0]
        stats_token = query_stats_var.set(stats)
        # Every Sentry event in this request (incl. ones from log lines) carries the id. The
        # Starlette integration forks the isolation scope per request outside this middleware.
        sentry_sdk.set_tag("request_id", request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != REQUEST_ID_HEADER
                ]
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            state = _state(scope)
            if state.get("client_disconnected"):
                status = 499  # nginx's "client closed request": no response was sent
            elif state.get("aborted"):
                status = 500  # started, then failed: the client got a broken response
            if self.access_log_enabled:
                access_log.info(
                    "request",
                    extra={
                        "request_id": request_id,
                        "method": scope.get("method"),
                        "path": route_template(scope),
                        "status": status,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                        "queries": int(stats[0]),
                        "db_ms": round(stats[1], 1),
                        "user_id": state.get("user_id"),
                        "org_id": state.get("org_id"),
                    },
                )
            query_stats_var.reset(stats_token)
            request_id_var.reset(token)


def internal_error_body(request_id: str) -> bytes:
    return json.dumps(
        {"code": "internal", "message": INTERNAL_MESSAGE, "request_id": request_id}
    ).encode()


class CatchAllMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except BodyTooLarge:
            raise  # `BodyCapMiddleware` (outside) answers 413
        except asyncio.CancelledError:
            # The client went away or the server is shutting down: not a fault to report.
            _state(scope)["client_disconnected"] = True
            raise
        except ClientDisconnect:
            _state(scope)["client_disconnected"] = True
            log.info("client disconnected before the request body was read")
        except Exception as exc:
            request_id = str(_state(scope).get("request_id") or request_id_var.get())
            # Capture first: Sentry's logging integration would otherwise report the log line
            # below, and dedupe would drop our capture (and its request id tag).
            try:
                capture_exception(exc)
            except Exception:  # pragma: no cover - reporting must never break the response
                log.warning("sentry capture failed")
            log.exception("unhandled error on %s %s", scope.get("method"), route_template(scope))
            if started:
                # Headers are already out: nothing safe to send. Re-raise so the server aborts
                # the connection cleanly (already captured and logged above).
                _state(scope)["aborted"] = True
                raise
            body = internal_error_body(request_id)
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})


# --- security headers ------------------------------------------------------------------------

_BASE_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-site"),
]
_JSON_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
_NO_STORE = (b"cache-control", b"no-store")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = str(scope.get("path", "")).startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = [h for h in _BASE_HEADERS if h[0] not in present]
                if is_api and b"cache-control" not in present:
                    extra.append(_NO_STORE)
                content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if content_type.startswith(b"application/json") and _JSON_CSP[0] not in present:
                    extra.append(_JSON_CSP)
                if self.hsts and _HSTS[0] not in present:
                    extra.append(_HSTS)
                message = {**message, "headers": headers + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# --- body cap --------------------------------------------------------------------------------

MAX_BODY_BYTES = 256 * 1024
TOO_LARGE_BODY = json.dumps(
    {"code": "payload_too_large", "message": "That's too large to send."}
).encode()


class BodyTooLarge(BaseException):  # a signal, caught by `BodyCapMiddleware`
    """A `BaseException`: FastAPI turns any `Exception` raised while reading the body into a
    400 "error parsing the body", which would hide the 413."""


class BodyCapMiddleware:
    """The largest legitimate body is a code submission (≤ 20 000 chars + test outputs)."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(TOO_LARGE_BODY)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": TOO_LARGE_BODY})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared > self.max_bytes:
                    await self._reject(send)
                    return
        received = 0
        started = False

        async def capped_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, tracking_send)
        except BodyTooLarge:
            if started:  # pragma: no cover - a body is read before any response
                raise
            await self._reject(send)
