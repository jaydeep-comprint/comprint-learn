"""Pure ASGI middleware (spec 015), not `BaseHTTPMiddleware`, so streaming and cancellation work.

Order, outermost first (see `app.main.create_app`):
request id → CORS → catch-all → app.

- `RequestIdMiddleware`: every request gets an id (a well-formed incoming `X-Request-ID`, else a
  new uuid4 hex), returned as `X-Request-ID`, kept in a contextvar for logs and Sentry, and in
  production one access log line per request (route template, never the raw URL).
- `CatchAllMiddleware`: an unhandled exception becomes `500 {"code": "internal", ...}` with the
  request id, never a stack trace; reported to Sentry and logged. It sits inside CORS, so the 500
  still carries the CORS headers (an `add_exception_handler(Exception)` would run outside them).
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

from app.core.observability import ACCESS_LOGGER, capture_exception, request_id_var

log = logging.getLogger(__name__)
access_log = logging.getLogger(ACCESS_LOGGER)

REQUEST_ID_HEADER = b"x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
INTERNAL_MESSAGE = "Something went wrong. Please try again."


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == REQUEST_ID_HEADER:
            try:
                text = value.decode("latin-1")
            except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes any bytes
                return None
            return text if _VALID_REQUEST_ID.match(text) else None
    return None


def _state(scope: Scope) -> dict[str, Any]:
    state: dict[str, Any] = scope.setdefault("state", {})
    return state


def route_template(scope: Scope) -> str:
    """The matched route's path template (`/api/v1/students/{student_id}`), else "(unmatched)"."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "(unmatched)"


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
            if self.access_log_enabled:
                state = _state(scope)
                access_log.info(
                    "request",
                    extra={
                        "request_id": request_id,
                        "method": scope.get("method"),
                        "path": route_template(scope),
                        "status": status,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                        "user_id": state.get("user_id"),
                        "org_id": state.get("org_id"),
                    },
                )
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
        except asyncio.CancelledError:
            # The client went away or the server is shutting down: not a fault to report.
            raise
        except ClientDisconnect:
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
                # Headers are already out: nothing safe to send; the server closes the connection.
                return
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
