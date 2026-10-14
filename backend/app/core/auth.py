"""Supabase access-token verification: JWTs signed with the project's asymmetric keys (JWKS),
or legacy HS256.

Raises `Unauthenticated` for any bad token, and `AuthUnavailable` when keys can't be fetched and
none are cached, so a Supabase outage returns 503 instead of signing everyone out.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt

from app.core.config import get_settings

logger = logging.getLogger(__name__)

AUDIENCE = "authenticated"
LEEWAY_S = 30
JWKS_TTL_S = 600.0
# An unknown `kid` forces at most one refetch per interval (no fetch amplification).
FORCED_REFETCH_MIN_INTERVAL_S = 30.0
JWKS_TIMEOUT_S = 5.0
ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256", "EdDSA"})

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class VerifiedToken:
    user_id: uuid.UUID
    issued_at: int  # `iat`, seconds since the epoch


class Unauthenticated(Exception):  # noqa: N818 - reads better at call sites
    """Missing, malformed, expired or otherwise invalid token."""


class AuthUnavailable(Exception):  # noqa: N818
    """Signing keys could not be fetched and none are cached."""


def http_jwks_fetcher(jwks_url: str) -> JwksFetcher:
    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_S) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data

    return fetch


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        fetch_jwks: JwksFetcher,
        hs256_secret: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = issuer
        self._fetch_jwks = fetch_jwks
        self._hs256_secret = hs256_secret
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._forced_at: float | None = None
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> VerifiedToken:
        """The user id (`sub`) and issue time (`iat`) of a valid access token."""
        if self._hs256_secret:
            claims = self._decode(token, self._hs256_secret, ["HS256"])
        else:
            try:
                header = jwt.get_unverified_header(token)
            except jwt.InvalidTokenError as exc:
                raise Unauthenticated from exc
            kid, alg = header.get("kid"), header.get("alg")
            if not isinstance(kid, str) or alg not in ASYMMETRIC_ALGORITHMS:
                raise Unauthenticated
            key = await self._key_for(kid)
            if key.algorithm_name != alg:
                raise Unauthenticated
            claims = self._decode(token, key.key, [alg])
        try:
            return VerifiedToken(uuid.UUID(str(claims["sub"])), int(claims["iat"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise Unauthenticated from exc

    def _decode(self, token: str, key: Any, algorithms: list[str]) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=AUDIENCE,
                issuer=self._issuer,
                leeway=LEEWAY_S,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.InvalidTokenError as exc:
            raise Unauthenticated from exc
        return claims

    async def _key_for(self, kid: str) -> jwt.PyJWK:
        now = self._clock()
        fresh = self._fetched_at is not None and now - self._fetched_at < JWKS_TTL_S
        if not fresh:
            await self._refresh(forced=False)
        if kid not in self._keys:
            can_force = self._forced_at is None or (
                self._clock() - self._forced_at >= FORCED_REFETCH_MIN_INTERVAL_S
            )
            if can_force:
                await self._refresh(forced=True)
        key = self._keys.get(kid)
        if key is None:
            raise Unauthenticated
        return key

    async def _refresh(self, *, forced: bool) -> None:
        async with self._lock:
            fresh = self._fetched_at is not None and self._clock() - self._fetched_at < JWKS_TTL_S
            if not forced and fresh:
                return  # another request refreshed while we waited for the lock
            if forced:
                self._forced_at = self._clock()
            try:
                data = await self._fetch_jwks()
                keys = {}
                for jwk in data.get("keys", []):
                    if not isinstance(jwk, dict) or not isinstance(jwk.get("kid"), str):
                        continue
                    try:
                        keys[jwk["kid"]] = jwt.PyJWK(jwk)
                    except jwt.PyJWTError:
                        continue  # unsupported key type: skip it, keep the rest
            except Exception as exc:
                logger.warning("JWKS fetch failed (%s)", type(exc).__name__)
                if not self._keys:
                    raise AuthUnavailable from exc
                # Keep serving the stale keys; try again in a little while, not on every request.
                self._fetched_at = self._clock() - JWKS_TTL_S + FORCED_REFETCH_MIN_INTERVAL_S
                return
            self._keys = keys
            self._fetched_at = self._clock()


@lru_cache
def get_token_verifier() -> TokenVerifier:
    """Process-wide verifier (keeps the JWKS cache). FastAPI dependency; tests override it."""
    settings = get_settings()
    base = settings.require_supabase_url()
    secret = settings.supabase_jwt_secret
    return TokenVerifier(
        issuer=f"{base}/auth/v1",
        fetch_jwks=http_jwks_fetcher(f"{base}/auth/v1/.well-known/jwks.json"),
        hs256_secret=secret.get_secret_value() if secret else None,
    )
