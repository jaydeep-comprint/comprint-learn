"""HS256 access tokens for the load test (spec 015 §3).

The load-test API runs with `SUPABASE_JWT_SECRET` set to a random per-run secret (the verifier's
existing HS256 path), so Locust can mint tokens for the seeded users: no Supabase auth users are
created and no sign-in endpoint is hit. Claims match what `app.core.auth.TokenVerifier` requires.
"""

import time
import uuid

import jwt

TTL_S = 3600  # run time + slack: a 10-minute run never sees an expired token


def mint(
    user_id: uuid.UUID | str, secret: str, supabase_url: str, *, now: int | None = None
) -> str:
    issued = int(time.time()) if now is None else now
    claims = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iss": f"{supabase_url.rstrip('/')}/auth/v1",
        "iat": issued,
        "exp": issued + TTL_S,
        "role": "authenticated",
    }
    return jwt.encode(claims, secret, algorithm="HS256")
