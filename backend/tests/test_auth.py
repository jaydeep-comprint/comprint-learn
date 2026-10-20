import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.auth import AuthUnavailable, TokenVerifier, Unauthenticated

ISSUER = "https://test-project.supabase.co/auth/v1"
USER_ID = uuid.uuid4()


def _ec_key(kid: str) -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "ES256", "use": "sig"})
    return private, jwk


KEY_A, JWK_A = _ec_key("key-a")
KEY_B, JWK_B = _ec_key("key-b")


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(USER_ID),
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _token(key: Any = KEY_A, kid: str = "key-a", **overrides: Any) -> str:
    return jwt.encode(_claims(**overrides), key, algorithm="ES256", headers={"kid": kid})


class FakeJwks:
    def __init__(self, *jwks: dict[str, Any]) -> None:
        self.keys = list(jwks)
        self.calls = 0
        self.fail = False

    async def __call__(self) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise OSError("unreachable")
        return {"keys": self.keys}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _verifier(fetch: FakeJwks, clock: Clock | None = None, **kw: Any) -> TokenVerifier:
    return TokenVerifier(issuer=ISSUER, fetch_jwks=fetch, clock=clock or Clock(), **kw)


async def test_valid_token_returns_sub() -> None:
    fetch = FakeJwks(JWK_A)
    assert (await _verifier(fetch).verify(_token())).user_id == USER_ID


async def test_jwks_cached_then_refreshed_after_ttl() -> None:
    fetch, clock = FakeJwks(JWK_A), Clock()
    v = _verifier(fetch, clock)
    await v.verify(_token())
    await v.verify(_token())
    assert fetch.calls == 1
    clock.t += 601
    await v.verify(_token())
    assert fetch.calls == 2


async def test_expired_token_rejected_with_leeway() -> None:
    v = _verifier(FakeJwks(JWK_A))
    now = int(time.time())
    assert (await v.verify(_token(exp=now - 10))).user_id == USER_ID  # within 30 s leeway
    with pytest.raises(Unauthenticated):
        await v.verify(_token(exp=now - 120))


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "anon"},
        {"iss": "https://evil.supabase.co/auth/v1"},
        {"exp": None},
        {"sub": None},
        {"sub": "not-a-uuid"},
        {"iat": None},
    ],
)
async def test_bad_claims_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(Unauthenticated):
        await _verifier(FakeJwks(JWK_A)).verify(_token(**overrides))


async def test_bad_signature_rejected() -> None:
    forged = _token(key=KEY_B, kid="key-a")  # signed by B, claims to be A
    with pytest.raises(Unauthenticated):
        await _verifier(FakeJwks(JWK_A)).verify(forged)


async def test_unknown_kid_refetches_once_then_rejects() -> None:
    fetch = FakeJwks(JWK_A)
    v = _verifier(fetch)
    with pytest.raises(Unauthenticated):
        await v.verify(_token(key=KEY_B, kid="key-b"))
    assert fetch.calls == 2
    # Another unknown kid straight away doesn't hammer the JWKS endpoint.
    with pytest.raises(Unauthenticated):
        await v.verify(_token(key=KEY_B, kid="key-b"))
    assert fetch.calls == 2


async def test_rotated_key_found_on_refetch() -> None:
    fetch = FakeJwks(JWK_A)
    v = _verifier(fetch)
    await v.verify(_token())
    fetch.keys.append(JWK_B)
    assert (await v.verify(_token(key=KEY_B, kid="key-b"))).user_id == USER_ID


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
async def test_malformed_token_rejected(token: str) -> None:
    with pytest.raises(Unauthenticated):
        await _verifier(FakeJwks(JWK_A)).verify(token)


async def test_hs256_token_rejected_without_legacy_secret() -> None:
    token = jwt.encode(_claims(), "x" * 32, algorithm="HS256", headers={"kid": "key-a"})
    with pytest.raises(Unauthenticated):
        await _verifier(FakeJwks(JWK_A)).verify(token)


async def test_jwks_unreachable_and_nothing_cached_is_unavailable() -> None:
    fetch = FakeJwks(JWK_A)
    fetch.fail = True
    with pytest.raises(AuthUnavailable):
        await _verifier(fetch).verify(_token())


async def test_jwks_unreachable_uses_stale_cache() -> None:
    fetch, clock = FakeJwks(JWK_A), Clock()
    v = _verifier(fetch, clock)
    await v.verify(_token())
    fetch.fail = True
    clock.t += 601
    assert (await v.verify(_token())).user_id == USER_ID


async def test_legacy_hs256_secret() -> None:
    secret = "legacy-secret-" + "x" * 32
    fetch = FakeJwks()
    v = _verifier(fetch, hs256_secret=secret)
    token = jwt.encode(_claims(), secret, algorithm="HS256")
    assert (await v.verify(token)).user_id == USER_ID
    assert fetch.calls == 0
    with pytest.raises(Unauthenticated):
        await v.verify(jwt.encode(_claims(), "wrong-secret-" + "y" * 32, algorithm="HS256"))
    with pytest.raises(Unauthenticated):
        await v.verify(_token())  # ES256 not accepted in legacy mode
