"""The hand-written migrations match the models (no drift)."""

import os
import subprocess
import sys

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, select, text

import app.models  # noqa: F401
from app.cli import DEFAULT_CONTENT_ROOT
from app.content.importer import import_tree
from app.core.config import get_settings
from app.db.base import Base
from app.models import Concept, ConceptState, ConceptStatus
from tests.conftest import BACKEND_DIR, DbApp
from tests.db_seed import seed_school

pytestmark = pytest.mark.db


def _diff(conn: Connection) -> list[object]:
    return list(compare_metadata(MigrationContext.configure(conn), Base.metadata))


async def test_models_match_migrations(db_app: DbApp) -> None:
    async with db_app.sessions() as session:
        conn = await session.connection()
        diff = await conn.run_sync(_diff)
    assert diff == []


async def test_0005_backfills_started_lessons_as_in_progress(db_app: DbApp) -> None:
    """A lesson 004 opened stays open after 0005: its `lesson_progress` row becomes an
    in-progress `concept_state` (and nobody is marked learned)."""
    issues, report = await import_tree(DEFAULT_CONTENT_ROOT, db_app.sessions)
    assert report is not None, [str(i) for i in issues]
    async with db_app.sessions() as session:
        school = await seed_school(session, "AAA")
        concept_id = await session.scalar(select(Concept.id).where(Concept.slug == "acceleration"))
    student = school.student_ids[3]

    env = {**os.environ, "DATABASE_URL": get_settings().test_database_url or ""}

    def alembic(*args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )

    await db_app.sessions.kw["bind"].dispose()
    alembic("downgrade", "0004_learn")
    try:
        async with db_app.sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO lesson_progress (org_id, student_id, concept_id, seen_steps, "
                    "last_step) VALUES (:org, :student, :concept, '{intro}', 'intro')"
                ),
                {"org": school.org_id, "student": student, "concept": concept_id},
            )
            await session.commit()
        await db_app.sessions.kw["bind"].dispose()
    finally:
        alembic("upgrade", "head")
    async with db_app.sessions() as session:
        rows = (await session.scalars(select(ConceptState))).all()
    assert [(r.student_id, r.concept_id, r.status) for r in rows] == [
        (student, concept_id, ConceptStatus.in_progress)
    ]
