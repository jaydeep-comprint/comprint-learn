"""Error tracking (Sentry, scrubbed) and logging (spec 015).

Nothing personal may reach Sentry or the logs: no names, usernames, answers, tutor text, request
bodies, query strings, cookies or auth headers. Sentry gets stack traces and ids only:
`user.id` (our `app_user.id`), `org_id`, `role`, `is_admin` and `request_id`.

- `init_sentry(settings)`: does nothing without `SENTRY_DSN` (the default, and always in tests).
- `before_send`: the last line of defence for every event, whatever the SDK attached.
- `configure_logging(settings)`: one JSON line per record in production; dev is unchanged.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import sentry_sdk
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app.core.errors import ApiProblem

if TYPE_CHECKING:
    from app.core.config import Settings

# The current request's id (set by `RequestIdMiddleware`); "-" outside a request.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
# Per-request database statement count and time [count, ms] (spec 015 load test: shows N+1s
# and round trips per endpoint in the access log). None outside a request.
query_stats_var: contextvars.ContextVar[list[float] | None] = contextvars.ContextVar(
    "query_stats", default=None
)

KEPT_HEADERS = frozenset({"user-agent"})
ACCESS_LOGGER = "app.access"
# Breadcrumb categories the SDK may attach whose `data` can hold URLs with query strings.
_HTTP_BREADCRUMBS = frozenset({"httplib", "httpx", "http"})


# Postgres error text adds a DETAIL line that echoes row values, e.g. a unique violation's
# `Key (org_id, lower(username))=(…, asha.v) already exists.` `hide_parameters` doesn't cover it.
# A DETAIL can span lines ("Failing row contains (...)" with student code or chat text), so remove
# everything up to the next section SQLAlchemy/asyncpg add (HINT, [SQL:, (Background on) or the end.
_PG_DETAIL = re.compile(r"(?ms)^([ \t]*)DETAIL:.*?(?=^[ \t]*(?:HINT:|\[SQL:|\(Background on)|\Z)")


def scrub_text(text: str) -> str:
    """Remove Postgres DETAIL sections (they echo row values: names, usernames, code)."""
    return _PG_DETAIL.sub(r"\1DETAIL: (removed)\n", text)


# --- Sentry ---------------------------------------------------------------------------------


def init_sentry(settings: Settings) -> bool:
    """Initialise the SDK when a DSN is set. Returns whether it did."""
    if settings.sentry_dsn is None:
        return False
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    # We capture ourselves (catch-all middleware, `ApiProblem` >= 500 with a fingerprint): the
    # integrations' own HTTP-status capture would double-report.
    no_status_capture: set[int] = set()
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        integrations=[
            StarletteIntegration(failed_request_status_codes=no_status_capture),
            FastApiIntegration(failed_request_status_codes=no_status_capture),
        ],
        environment=settings.environment,
        release=settings.git_sha,
        send_default_pii=False,
        include_local_variables=False,  # locals can hold names, answers, tutor text
        max_request_body_size="never",
        traces_sample_rate=0,  # errors only
        # Our hook works on plain dicts; the SDK's `Event` is a TypedDict of the same shape.
        before_send=cast(Any, before_send),
        before_breadcrumb=before_breadcrumb,
    )
    return True


def _scrub_request(request: dict[str, Any]) -> None:
    for key in ("data", "cookies", "query_string", "env"):
        request.pop(key, None)
    url = request.get("url")
    if isinstance(url, str):
        request["url"] = _path_only(url)
    headers = request.get("headers")
    if isinstance(headers, Mapping):
        request["headers"] = {k: v for k, v in headers.items() if k.lower() in KEPT_HEADERS}
    elif headers is not None:
        request.pop("headers")


def _path_only(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    return parts.path


def _scrub_frames(event: dict[str, Any]) -> None:
    """Defence in depth on top of `include_local_variables=False`."""
    for exc in (event.get("exception") or {}).get("values") or []:
        for frame in (exc.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    for thread in (event.get("threads") or {}).get("values") or []:
        for frame in (thread.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)


def _scrub_breadcrumb(crumb: dict[str, Any]) -> dict[str, Any] | None:
    category = crumb.get("category")
    if category in _HTTP_BREADCRUMBS or crumb.get("type") == "http":
        data = crumb.get("data") or {}
        kept: dict[str, Any] = {}
        if isinstance(data.get("url"), str):
            kept["url"] = _path_only(data["url"])
        for key in ("method", "status_code"):
            if key in data:
                kept[key] = data[key]
        crumb["data"] = kept
        return crumb
    # Log breadcrumbs carry the formatted message, which may hold ids but must hold nothing more;
    # drop their extra data.
    crumb.pop("data", None)
    if isinstance(crumb.get("message"), str):
        crumb["message"] = scrub_text(crumb["message"])
    return crumb


def before_breadcrumb(crumb: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    return _scrub_breadcrumb(crumb)


def _validation_summary(exc: BaseException) -> str | None:
    """Error types and field paths only: validation messages can echo the input."""
    errors: list[Any] | None = None
    if isinstance(exc, ValidationError):
        errors = list(exc.errors(include_input=False, include_url=False, include_context=False))
    else:
        from fastapi.exceptions import RequestValidationError, ResponseValidationError

        if isinstance(exc, RequestValidationError | ResponseValidationError):
            errors = list(exc.errors())
    if errors is None:
        return None
    parts = []
    for err in errors:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{err.get('type', 'error')} at {loc or '-'}")
    return "; ".join(parts) or "validation error"


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    exc_info = hint.get("exc_info")
    exc = exc_info[1] if exc_info else None
    if isinstance(exc, ApiProblem) and exc.status < 500:
        return None
    if isinstance(exc, HTTPException) and exc.status_code < 500:
        return None

    request = event.get("request")
    if isinstance(request, dict):
        _scrub_request(request)
    _scrub_frames(event)
    event.pop("extra", None)
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if "id" in user else {}

    crumbs = event.get("breadcrumbs")
    if isinstance(crumbs, dict):
        values = crumbs.get("values") or []
        crumbs["values"] = [c for c in (_scrub_breadcrumb(dict(v)) for v in values) if c]

    for value in (event.get("exception") or {}).get("values") or []:
        if isinstance(value.get("value"), str):
            value["value"] = scrub_text(value["value"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for key in ("message", "formatted"):
            if isinstance(logentry.get(key), str):
                logentry[key] = scrub_text(logentry[key])
        logentry.pop("params", None)
    if isinstance(event.get("message"), str):
        event["message"] = scrub_text(event["message"])

    if exc is not None:
        summary = _validation_summary(exc)
        if summary is not None:
            for value in (event.get("exception") or {}).get("values") or []:
                value["value"] = summary
            if "logentry" in event:
                event["logentry"] = {"message": summary}
            event.pop("message", None)
    return event


def set_user_context(*, user_id: str, org_id: str, role: str, is_admin: bool) -> None:
    """Ids only. No-op when Sentry isn't initialised."""
    scope = sentry_sdk.get_isolation_scope()
    scope.set_user({"id": user_id})
    scope.set_tag("org_id", org_id)
    scope.set_tag("role", role)
    scope.set_tag("is_admin", str(is_admin).lower())


def capture_exception(exc: BaseException, *, fingerprint: list[str] | None = None) -> str | None:
    """Report `exc` with the current request id. Returns the event id (None when Sentry is off)."""
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("request_id", request_id_var.get())
        if fingerprint is not None:
            scope.fingerprint = fingerprint
        return sentry_sdk.capture_exception(exc)


# --- Logging --------------------------------------------------------------------------------


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


_ACCESS_FIELDS = ("method", "path", "status", "ms", "queries", "db_ms", "user_id", "org_id")


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, request_id (+ access fields)."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub_text(record.getMessage()),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for field in _ACCESS_FIELDS:
            if hasattr(record, field):
                data[field] = getattr(record, field)
        if record.exc_info:
            data["exc"] = scrub_text(self.formatException(record.exc_info))
        return json.dumps(data, default=str)


def configure_logging(settings: Settings) -> None:
    """Production: JSON on root, `uvicorn.error` and the access logger; `uvicorn.access` off (it
    prints raw URLs with query strings). Other environments are left as they are."""
    if not settings.is_production:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", ACCESS_LOGGER):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
