import pytest
from sqlalchemy import text

from tests.conftest import DbApp

pytestmark = pytest.mark.db


async def test_every_public_table_has_rls_enabled(db_app: DbApp) -> None:
    async with db_app.sessions() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
                )
            )
        ).all()
    tables = {name: rls for name, rls in rows}
    assert {"alembic_version", "organization", "app_user", "enrollment"} <= set(tables)
    content = {"course", "chapter", "concept", "concept_prereq", "knowledge_point"}
    assert content | {"kp_key_prereq", "misconception", "item"} <= set(tables)
    assert [name for name, rls in tables.items() if not rls] == []
