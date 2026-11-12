"""Rate limits (spec 015): in-process token buckets, no Redis.

- **Per signed-in user**, never per IP: a school lab shares one public IP. The user's bucket is
  checked in the auth dependency right after the token verifies (keyed by its `sub`) and before
  the `app_user` lookup, so a flood costs no database query.
  Writes (POST/PATCH/PUT/DELETE): 120/min, burst 40. Reads: 600/min, burst 120.
- **Expensive endpoints** also take their own bucket (`limit("export")` etc.), on top of the
  general one.
- **Unauthenticated** (missing or invalid token) requests are limited per IP: 300/min.
- Over the limit → 429 `rate_limited` with `Retry-After` (seconds).

Limits are per process: with N workers the effective limit is up to N times. Buckets idle for
10 minutes are dropped once they would have refilled anyway (so hourly buckets keep their
state). `RATE_LIMIT_ENABLED=false` switches everything off (the test default).
"""

import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from starlette.requests import Request

from app.core.config import get_settings
from app.core.errors import ApiProblem

if TYPE_CHECKING:
    from app.core.config import Settings

RATE_LIMITED_MESSAGE = "Too many requests. Wait a moment and try again."
IDLE_S = 600.0
SWEEP_EVERY_S = 60.0
WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Defaults (settings can lower them, e.g. for the browser check). "120/min, burst 40" means a
# bucket of 40 tokens refilled at 2 per second.
WRITE_PER_MIN = 120
WRITE_BURST = 40
READ_PER_MIN = 600
READ_BURST = 120
UNAUTH_IP_PER_MIN = 300


@dataclass(frozen=True)
class Limit:
    capacity: float
    per_second: float

    @classmethod
    def per_minute(cls, count: float, burst: float | None = None) -> Self:
        return cls(capacity=burst if burst is not None else count, per_second=count / 60)

    @classmethod
    def per_hour(cls, count: float) -> Self:
        return cls(capacity=count, per_second=count / 3600)


# Expensive endpoints: their own bucket, per user.
EXPENSIVE: dict[str, Limit] = {
    "export": Limit.per_hour(5),  # student export, per admin
    "bulk_students": Limit.per_hour(10),  # bulk student creation, per teacher
    "consent_bulk": Limit.per_minute(30),
}


@dataclass
class _Bucket:
    tokens: float
    updated: float
    limit: Limit

    def full_at(self) -> float:
        """When the bucket is back to capacity: dropping it earlier would refill it for free
        (an hourly bucket idle for 10 minutes is still far from full)."""
        return self.updated + (self.limit.capacity - self.tokens) / self.limit.per_second


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock  # monotonic: a host clock jump can't refill or drain buckets
        self.buckets: dict[tuple[str, str], _Bucket] = {}
        self._last_sweep = clock()

    def hit(self, kind: str, key: str, limit: Limit) -> float | None:
        """Take one token. None when allowed, else the seconds until one is available."""
        now = self.clock()
        self._sweep(now)
        bucket = self.buckets.get((kind, key))
        if bucket is None:
            bucket = self.buckets[(kind, key)] = _Bucket(limit.capacity, now, limit)
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(limit.capacity, bucket.tokens + elapsed * limit.per_second)
            bucket.updated = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return None
        return (1 - bucket.tokens) / limit.per_second

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < SWEEP_EVERY_S:
            return
        self._last_sweep = now
        idle = [
            k for k, b in self.buckets.items() if now - b.updated >= IDLE_S and now >= b.full_at()
        ]
        for k in idle:
            del self.buckets[k]

    def reset(self) -> None:
        self.buckets.clear()


limiter = RateLimiter()


def rate_limited(retry_after: float) -> ApiProblem:
    return ApiProblem(
        429,
        "rate_limited",
        RATE_LIMITED_MESSAGE,
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )


def _user_limit(settings: "Settings", method: str) -> tuple[str, Limit]:
    if method.upper() in WRITE_METHODS:
        return "write", Limit.per_minute(
            settings.rate_limit_write_per_min, settings.rate_limit_write_burst
        )
    return "read", Limit.per_minute(
        settings.rate_limit_read_per_min, settings.rate_limit_read_burst
    )


def check_user(request: Request, user_id: uuid.UUID) -> None:
    """The general per-user bucket. Raises 429."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    kind, limit = _user_limit(settings, request.method)
    wait = limiter.hit(kind, str(user_id), limit)
    if wait is not None:
        raise rate_limited(wait)


def client_ip(request: Request, trusted_proxy_count: int) -> str:
    """The socket address, or with N trusted proxies the Nth address from the right of
    `X-Forwarded-For` (the one our outermost trusted proxy saw)."""
    if trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        addrs = [a.strip() for a in forwarded.split(",") if a.strip()]
        if len(addrs) >= trusted_proxy_count:
            return addrs[-trusted_proxy_count]
    return request.client.host if request.client else "unknown"


def check_unauthenticated(request: Request) -> None:
    """Missing or invalid token: the per-IP bucket. Raises 429 instead of the 401 when empty."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    ip = client_ip(request, settings.trusted_proxy_count)
    wait = limiter.hit("ip", ip, Limit.per_minute(UNAUTH_IP_PER_MIN))
    if wait is not None:
        raise rate_limited(wait)


def check_expensive(name: str, user_id: uuid.UUID) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    wait = limiter.hit(name, str(user_id), EXPENSIVE[name])
    if wait is not None:
        raise rate_limited(wait)


def limit(name: str) -> Callable[..., Awaitable[None]]:
    """A route dependency for an expensive endpoint: its own bucket, after auth (the general
    bucket was already taken by the auth dependency)."""
    if name not in EXPENSIVE:
        raise ValueError(f"unknown rate limit {name!r}")
    # Imported here: deps imports this module.
    from typing import Annotated

    from fastapi import Depends

    from app.api.deps import CurrentUser, get_current_user

    async def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> None:
        check_expensive(name, user.id)

    dependency.__name__ = f"limit_{name}"
    return dependency
