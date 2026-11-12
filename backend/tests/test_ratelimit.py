"""Spec 015 §4: per-user token buckets, the per-IP bucket for bad tokens, expensive endpoints."""

import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import AnyUser
from app.core import ratelimit
from app.core.auth import AuthUnavailable, Unauthenticated, VerifiedToken, get_token_verifier
from app.core.config import get_settings
from app.core.ratelimit import EXPENSIVE, READ_BURST, Limit, RateLimiter, client_ip, limit
from app.db.session import get_session
from app.main import create_app
from app.models import AppUser, Role, UserStatus

ORG = uuid.uuid4()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- bucket maths ---------------------------------------------------------------------------


def test_burst_then_refill_at_the_rate() -> None:
    clock = FakeClock()
    rl = RateLimiter(clock)
    write = Limit.per_minute(120, 40)  # capacity 40, 2 tokens/s
    assert all(rl.hit("write", "u", write) is None for _ in range(40))
    wait = rl.hit("write", "u", write)
    assert wait == pytest.approx(0.5)
    clock.now += 0.5
    assert rl.hit("write", "u", write) is None
    assert rl.hit("write", "u", write) == pytest.approx(0.5)
    clock.now += 60  # refills to capacity, never beyond
    assert sum(rl.hit("write", "u", write) is None for _ in range(100)) == 40


def test_keys_and_kinds_are_independent() -> None:
    rl = RateLimiter(FakeClock())
    tiny = Limit(capacity=1, per_second=0.01)
    assert rl.hit("read", "a", tiny) is None
    assert rl.hit("read", "a", tiny) is not None
    assert rl.hit("read", "b", tiny) is None
    assert rl.hit("write", "a", tiny) is None


def test_idle_buckets_are_dropped() -> None:
    clock = FakeClock()
    rl = RateLimiter(clock)
    rl.hit("read", "old", Limit.per_minute(600, 120))
    clock.now += ratelimit.IDLE_S - 1
    rl.hit("read", "fresh", Limit.per_minute(600, 120))
    assert set(rl.buckets) == {("read", "old"), ("read", "fresh")}
    clock.now += ratelimit.SWEEP_EVERY_S + 1  # past the next sweep: "old" idle > IDLE_S
    rl.hit("read", "fresh", Limit.per_minute(600, 120))
    assert set(rl.buckets) == {("read", "fresh")}


def test_clock_going_backwards_never_adds_tokens() -> None:
    clock = FakeClock()
    rl = RateLimiter(clock)
    one = Limit(capacity=1, per_second=1)
    assert rl.hit("k", "u", one) is None
    clock.now -= 100
    assert rl.hit("k", "u", one) is not None


def test_defaults_match_the_spec() -> None:
    get_settings.cache_clear()
    s = get_settings()
    assert READ_BURST == 120
    assert (s.rate_limit_read_per_min, s.rate_limit_read_burst) == (600, 120)
    assert (s.rate_limit_write_per_min, s.rate_limit_write_burst) == (120, 40)
    assert EXPENSIVE["export"] == Limit(5, 5 / 3600)
    assert EXPENSIVE["bulk_students"] == Limit(10, 10 / 3600)
    assert EXPENSIVE["consent_bulk"] == Limit(30, 0.5)


# --- client ip -------------------------------------------------------------------------------


class _Req:
    def __init__(self, xff: str | None, host: str = "10.0.0.9") -> None:
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = type("C", (), {"host": host})()


@pytest.mark.parametrize(
    ("xff", "count", "expected"),
    [
        ("1.1.1.1, 2.2.2.2", 0, "10.0.0.9"),  # untrusted header ignored
        ("1.1.1.1, 2.2.2.2", 1, "2.2.2.2"),
        ("spoof, 1.1.1.1, 2.2.2.2", 2, "1.1.1.1"),
        ("2.2.2.2", 2, "10.0.0.9"),  # fewer entries than proxies: the socket
        (None, 1, "10.0.0.9"),
    ],
)
def test_client_ip(xff: str | None, count: int, expected: str) -> None:
    assert client_ip(_Req(xff), count) == expected  # type: ignore[arg-type]


# --- through the app -------------------------------------------------------------------------


def _user(**kw: Any) -> AppUser:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org_id": ORG,
        "role": Role.teacher,
        "is_admin": True,
        "display_name": "x",
        "status": UserStatus.active,
        "must_change_password": False,
    }
    values.update(kw)
    return AppUser(**values)


class FakeVerifier:
    unavailable = False

    async def verify(self, token: str) -> VerifiedToken:
        if self.unavailable:
            raise AuthUnavailable
        if not token.startswith("ok-"):
            raise Unauthenticated
        return VerifiedToken(uuid.UUID(token[3:]), int(time.time()))


class FakeSession:
    def __init__(self, users: list[AppUser]) -> None:
        self.users = {u.id: u for u in users}
        self.gets = 0

    async def get(self, _model: type, id_: uuid.UUID) -> AppUser | None:
        self.gets += 1
        return self.users.get(id_)

    async def commit(self) -> None:
        pass


@pytest.fixture
def limiter_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    get_settings.cache_clear()
    ratelimit.limiter.reset()
    yield
    ratelimit.limiter.reset()


async def _client(
    users: list[AppUser], verifier: FakeVerifier | None = None
) -> tuple[AsyncClient, FakeSession, FastAPI]:
    app = create_app()
    session = FakeSession(users)

    async def fake_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_token_verifier] = lambda: verifier or FakeVerifier()

    @app.get("/t/read")
    async def read(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    @app.post("/t/write")
    async def write(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    @app.get("/t/export", dependencies=[Depends(limit("export"))])
    async def export(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, session, app


def _auth(user: AppUser) -> dict[str, str]:
    return {"Authorization": f"Bearer ok-{user.id}"}


async def test_429_with_retry_after_and_no_db_query_once_limited(limiter_on: None) -> None:
    user = _user()
    client, session, _ = await _client([user])
    async with client:
        codes = [
            (await client.post("/t/write", headers=_auth(user))).status_code for _ in range(41)
        ]
        assert codes[:40] == [200] * 40
        assert codes[40] == 429
        gets_before = session.gets
        resp = await client.post("/t/write", headers=_auth(user))
    assert resp.status_code == 429
    assert resp.json() == {
        "code": "rate_limited",
        "message": "Too many requests. Wait a moment and try again.",
    }
    assert resp.headers["retry-after"] == "1"
    assert session.gets == gets_before  # limited before the app_user lookup


async def test_80_students_behind_one_ip_are_independent(limiter_on: None) -> None:
    users = [_user(role=Role.student, is_admin=False) for _ in range(80)]
    client, _, _ = await _client(users)
    async with client:
        for _ in range(3):  # a lesson's burst of writes for the whole lab at once
            for u in users:
                resp = await client.post("/t/write", headers=_auth(u))
                assert resp.status_code == 200


async def test_reads_and_writes_have_separate_buckets(limiter_on: None) -> None:
    user = _user()
    client, _, _ = await _client([user])
    async with client:
        for _ in range(40):
            await client.post("/t/write", headers=_auth(user))
        assert (await client.post("/t/write", headers=_auth(user))).status_code == 429
        assert (await client.get("/t/read", headers=_auth(user))).status_code == 200


async def test_per_ip_limit_only_for_missing_or_invalid_tokens(
    limiter_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ratelimit, "UNAUTH_IP_PER_MIN", 3)
    user = _user()
    verifier = FakeVerifier()
    client, _, _ = await _client([user], verifier)
    async with client:
        codes = [
            (await client.get("/t/read")).status_code,
            (await client.get("/t/read", headers={"Authorization": "Bearer junk"})).status_code,
            (await client.get("/t/read")).status_code,
            (await client.get("/t/read")).status_code,
        ]
        assert codes == [401, 401, 401, 429]
        # A valid token from the same IP is unaffected.
        assert (await client.get("/t/read", headers=_auth(user))).status_code == 200
        # 503 auth_unavailable doesn't count (and isn't limited).
        ratelimit.limiter.reset()
        verifier.unavailable = True
        codes = [(await client.get("/t/read", headers=_auth(user))).status_code for _ in range(5)]
        assert codes == [503] * 5
        verifier.unavailable = False
        assert (await client.get("/t/read")).status_code == 401


async def test_deactivated_users_do_not_use_the_ip_bucket(
    limiter_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ratelimit, "UNAUTH_IP_PER_MIN", 1)
    gone = _user(status=UserStatus.deactivated)
    client, _, _ = await _client([gone])
    async with client:
        for _ in range(3):
            assert (await client.get("/t/read", headers=_auth(gone))).status_code == 401
        assert (await client.get("/t/read")).status_code == 401  # IP bucket still full


async def test_expensive_bucket_and_general_bucket_both_consumed(limiter_on: None) -> None:
    user = _user()
    client, _, _ = await _client([user])
    async with client:
        codes = [(await client.get("/t/export", headers=_auth(user))).status_code for _ in range(6)]
        assert codes == [200] * 5 + [429]
    assert ratelimit.limiter.buckets[("export", str(user.id))].tokens < 1
    # The general read bucket also took one token per request.
    assert ratelimit.limiter.buckets[("read", str(user.id))].tokens == pytest.approx(
        READ_BURST - 6, abs=0.5
    )


async def test_health_and_unmatched_paths_are_not_limited(
    limiter_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ratelimit, "UNAUTH_IP_PER_MIN", 1)
    client, _, app = await _client([])

    async def ok_session() -> AsyncIterator[Any]:
        class S:
            async def execute(self, _q: Any) -> None:
                return None

        yield S()

    app.dependency_overrides[get_session] = ok_session
    async with client:
        for _ in range(5):
            assert (await client.get("/api/v1/health")).status_code == 200
            assert (await client.get("/api/v1/nope")).status_code == 404


async def test_disabled_by_default_in_tests() -> None:
    get_settings.cache_clear()
    ratelimit.limiter.reset()
    user = _user()
    client, _, _ = await _client([user])
    async with client:
        codes = {
            (await client.post("/t/write", headers=_auth(user))).status_code for _ in range(60)
        }
    assert codes == {200}
    assert not ratelimit.limiter.buckets


def test_expensive_routes_use_their_buckets() -> None:
    from fastapi.routing import iter_route_contexts

    def calls(dep: Any) -> set[str]:
        out: set[str] = set()
        for sub in dep.dependencies:
            if sub.call is not None:
                out.add(getattr(sub.call, "__name__", ""))
            out |= calls(sub)
        return out

    found = {}
    for ctx in iter_route_contexts(create_app().routes):
        dependant = getattr(ctx, "dependant", None)
        if dependant is None:
            continue
        for method in ctx.methods or ():
            found[(method, ctx.path_format)] = calls(dependant)
    assert "limit_export" in found[("GET", "/api/v1/students/{student_id}/export")]
    assert "limit_bulk_students" in found[("POST", "/api/v1/classes/{class_id}/students")]
    assert "limit_consent_bulk" in found[("POST", "/api/v1/students/consent")]


def test_hourly_buckets_survive_the_idle_sweep() -> None:
    """Export is 5/hour: using all 5, waiting 11 minutes and asking again must still be limited."""
    clock = FakeClock()
    rl = RateLimiter(clock)
    export = EXPENSIVE["export"]
    assert all(rl.hit("export", "admin", export) is None for _ in range(5))
    clock.now += 11 * 60  # past IDLE_S and a sweep; only ~0.9 token refilled
    rl.hit("read", "someone", Limit.per_minute(600, 120))  # triggers the sweep
    assert ("export", "admin") in rl.buckets
    assert rl.hit("export", "admin", export) is not None
    clock.now += 60 * 60  # an hour later it's full again, and droppable
    rl.hit("read", "someone", Limit.per_minute(600, 120))
    assert ("export", "admin") not in rl.buckets
