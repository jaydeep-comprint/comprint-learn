"""The hand-written migrations match the models (no drift)."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection

import app.models  # noqa: F401
from app.db.base import Base
from tests.conftest import DbApp

pytestmark = pytest.mark.db


def _diff(conn: Connection) -> list[object]:
    return list(compare_metadata(MigrationContext.configure(conn), Base.metadata))


async def test_models_match_migrations(db_app: DbApp) -> None:
    async with db_app.sessions() as session:
        conn = await session.connection()
        diff = await conn.run_sync(_diff)
    assert diff == []
