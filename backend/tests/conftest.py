import os
from collections.abc import AsyncIterator, Iterator

# Set before any app import: `make check` must run without backend/.env or a network.
# Env vars win over backend/.env, so a developer's real DATABASE_URL is never used by offline tests.
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
# Empty = unset, and it overrides a legacy secret in a developer's backend/.env.
os.environ["SUPABASE_JWT_SECRET"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-role-key"

import pytest

from app.core.config import get_settings
from app.db.session import dispose_engine

DB_SKIP_MESSAGE = "TEST_DATABASE_URL not set; skipping DB tests (run 'make test-db' with it set)"
DB_REQUIRED_MESSAGE = (
    "TEST_DATABASE_URL is not set. `make test-db` needs it (env var or backend/.env), "
    "pointing at a separate test Supabase project."
)


@pytest.fixture(autouse=True)
async def _fresh_settings_and_engine() -> AsyncIterator[None]:
    get_settings.cache_clear()
    yield
    await dispose_engine()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _require_test_db(request: pytest.FixtureRequest) -> Iterator[None]:
    """`db` tests skip without TEST_DATABASE_URL, or fail under `make test-db` (REQUIRE_DB=1)."""
    if request.node.get_closest_marker("db") is not None and not get_settings().test_database_url:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(DB_REQUIRED_MESSAGE, pytrace=False)
        pytest.skip(DB_SKIP_MESSAGE)
    yield
