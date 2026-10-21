import os
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

# Set before any app import: `make check` must run without backend/.env or a network.
# Env vars win over backend/.env, so a developer's real DATABASE_URL is never used by offline tests.
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
# Empty = unset, and it overrides a legacy secret in a developer's backend/.env.
os.environ["SUPABASE_JWT_SECRET"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-role-key"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import Unauthenticated, VerifiedToken, get_token_verifier
from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.main import create_app
from app.services.supabase_admin import get_supabase_admin
from tests.fakes import FakeSupabaseAdmin

DB_SKIP_MESSAGE = "TEST_DATABASE_URL not set; skipping DB tests (run 'make test-db' with it set)"
DB_REQUIRED_MESSAGE = (
    "TEST_DATABASE_URL is not set. `make test-db` needs it (env var or backend/.env), "
    "pointing at a separate test Supabase project."
)


@pytest.fixture(autouse=True)
async def _fresh_settings_and_engine(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Offline tests get a fresh engine; DB tests share one (all point at TEST_DATABASE_URL)."""
    shared = request.node.get_closest_marker("db") is not None
    get_settings.cache_clear()
    if not shared:
        await dispose_engine()  # never hand an offline test the shared test-DB engine
    yield
    if not shared:
        await dispose_engine()
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
async def _dispose_shared_engine() -> AsyncIterator[None]:
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
def _require_test_db(request: pytest.FixtureRequest) -> Iterator[None]:
    """`db` tests skip without TEST_DATABASE_URL, or fail under `make test-db` (REQUIRE_DB=1)."""
    if request.node.get_closest_marker("db") is not None and not get_settings().test_database_url:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(DB_REQUIRED_MESSAGE, pytrace=False)
        pytest.skip(DB_SKIP_MESSAGE)
    yield


# --- Real-database fixtures (only used by `db` tests) ---------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
TENANT_TABLES = "organization, app_user, school_class, class_teacher, enrollment"
CONTENT_TABLES = (
    "course, chapter, concept, concept_prereq, knowledge_point, kp_key_prereq, misconception, item"
)


@pytest.fixture(scope="session")
def migrated_test_db() -> str:
    """Rebuilds the test project's schema once per run: downgrade to base, then upgrade head."""
    url = get_settings().test_database_url
    assert url
    env = {**os.environ, "DATABASE_URL": url}
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )
    return url


class FakeVerifier:
    """Tokens are `ok-<user id>` (issued now) or `ok-<user id>@<iat>`; anything else is rejected."""

    async def verify(self, token: str) -> VerifiedToken:
        if not token.startswith("ok-"):
            raise Unauthenticated
        user_id, _, iat = token[3:].partition("@")
        try:
            return VerifiedToken(uuid.UUID(user_id), int(iat) if iat else int(time.time()))
        except ValueError as exc:
            raise Unauthenticated from exc


@dataclass
class DbApp:
    client: AsyncClient
    admin: FakeSupabaseAdmin
    sessions: async_sessionmaker[AsyncSession]

    @staticmethod
    def auth(user_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer ok-{user_id}"}


@pytest.fixture
async def db_app(migrated_test_db: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[DbApp]:
    monkeypatch.setenv("DATABASE_URL", migrated_test_db)
    get_settings.cache_clear()
    sessions = get_sessionmaker()
    async with sessions() as session:
        await session.execute(text(f"TRUNCATE {TENANT_TABLES}, {CONTENT_TABLES} CASCADE"))
        await session.commit()

    fake_admin = FakeSupabaseAdmin()
    app = create_app()
    app.dependency_overrides[get_supabase_admin] = lambda: fake_admin
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield DbApp(client=client, admin=fake_admin, sessions=sessions)
