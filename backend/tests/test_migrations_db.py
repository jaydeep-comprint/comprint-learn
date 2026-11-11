"""The hand-written migrations match the models (no drift)."""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, select, text

import app.models  # noqa: F401
from app.cli import DEFAULT_CONTENT_ROOT
from app.content.importer import import_tree
from app.core.config import get_settings
from app.db.base import Base
from app.models import (
    Concept,
    ConceptState,
    ConceptStatus,
    ReviewCard,
    ReviewLog,
    ReviewSource,
)
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


async def test_0006_round_trip_drops_practice_rows(db_app: DbApp) -> None:
    """0006 down and up again with a practice session and multi-step step rows in place."""
    issues, report = await import_tree(DEFAULT_CONTENT_ROOT, db_app.sessions)
    assert report is not None, [str(i) for i in issues]
    async with db_app.sessions() as session:
        school = await seed_school(session, "AAA")
        concept_id = await session.scalar(select(Concept.id).where(Concept.slug == "acceleration"))
        item_id = await session.scalar(
            text(
                "SELECT id FROM item WHERE concept_id = :c AND kind = 'practice' AND "
                "type = 'multistep' LIMIT 1"
            ),
            {"c": concept_id},
        )
        session_id = await session.scalar(
            text(
                "INSERT INTO practice_session (id, org_id, student_id, kind, concept_id, status, "
                "current_item_id, current_position) VALUES (gen_random_uuid(), :org, :student, "
                "'practice', :concept, 'active', :item, 1) RETURNING id"
            ),
            {
                "org": school.org_id,
                "student": school.student_ids[3],
                "concept": concept_id,
                "item": item_id,
            },
        )
        for step in (0, 1):
            await session.execute(
                text(
                    "INSERT INTO attempt (id, org_id, student_id, item_id, item_version, context, "
                    "response, correct, time_taken_ms, session_id, position, step) VALUES "
                    "(gen_random_uuid(), :org, :student, :item, 1, 'practice', '{}', true, 1000, "
                    ":session, 1, :step)"
                ),
                {
                    "org": school.org_id,
                    "student": school.student_ids[3],
                    "item": item_id,
                    "session": session_id,
                    "step": step,
                },
            )
        await session.commit()

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
    alembic("downgrade", "0005_kp_flow")
    try:
        async with db_app.sessions() as session:
            assert await session.scalar(text("SELECT count(*) FROM attempt")) == 0
            assert await session.scalar(text("SELECT count(*) FROM practice_session")) == 0
        await db_app.sessions.kw["bind"].dispose()
    finally:
        alembic("upgrade", "head")
    async with db_app.sessions() as session:
        conn = await session.connection()
        assert await conn.run_sync(_diff) == []


async def test_0008_backfills_review_cards_from_learned_at(db_app: DbApp) -> None:
    """Every learned concept with gradable items gets a card after 0008, as if `learned_at` were
    a first Good review (so one learned long ago is already due), logged as `backfill`."""
    issues, report = await import_tree(DEFAULT_CONTENT_ROOT, db_app.sessions)
    assert report is not None, [str(i) for i in issues]
    async with db_app.sessions() as session:
        school = await seed_school(session, "AAA")
        concept_id = await session.scalar(select(Concept.id).where(Concept.slug == "acceleration"))
    student = school.student_ids[3]
    learned_at = datetime.now(UTC) - timedelta(days=60)
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
    alembic("downgrade", "0007_xp")
    try:
        async with db_app.sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO concept_state (org_id, student_id, concept_id, status, source, "
                    "learned_at) VALUES (:org, :student, :concept, 'learned', 'lesson', :at)"
                ),
                {"org": school.org_id, "student": student, "concept": concept_id, "at": learned_at},
            )
            await session.commit()
        await db_app.sessions.kw["bind"].dispose()
    finally:
        alembic("upgrade", "head")
    async with db_app.sessions() as session:
        cards = (await session.scalars(select(ReviewCard))).all()
        logs = (await session.scalars(select(ReviewLog))).all()
    assert [(c.student_id, c.concept_id) for c in cards] == [(student, concept_id)]
    card = cards[0]
    assert card.last_review == learned_at and card.reps == 1
    assert learned_at < card.due < datetime.now(UTC)  # learned long ago: already due
    assert [(e.source, e.rating) for e in logs] == [(ReviewSource.backfill, 3)]


async def test_0013_round_trip_keeps_erased_rows_as_deactivated(db_app: DbApp) -> None:
    """0013 down and up with an erased student and an audit event: the erased row comes back as
    deactivated (still anonymised); `erased` stays in `user_status` (Postgres can't drop it)."""
    async with db_app.sessions() as session:
        school = await seed_school(session, "AAA")
        student = school.student_ids[3]
        await session.execute(
            text(
                "UPDATE app_user SET status = 'erased', erased_at = now(), "
                "display_name = 'Erased student', username = 'erased-0123456789ab' WHERE id = :s"
            ),
            {"s": student},
        )
        await session.execute(
            text(
                "INSERT INTO audit_event (id, org_id, actor_id, action, target_id) VALUES "
                "(gen_random_uuid(), :org, NULL, 'erase_completed', :s)"
            ),
            {"org": school.org_id, "s": student},
        )
        await session.commit()

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
    alembic("downgrade", "0012_placement")
    try:
        async with db_app.sessions() as session:
            row = (
                await session.execute(
                    text("SELECT status::text, display_name FROM app_user WHERE id = :s"),
                    {"s": student},
                )
            ).one()
            assert tuple(row) == ("deactivated", "Erased student")
            assert await session.scalar(text("SELECT to_regclass('public.audit_event')")) is None
        await db_app.sessions.kw["bind"].dispose()
    finally:
        alembic("upgrade", "head")
    async with db_app.sessions() as session:
        conn = await session.connection()
        assert await conn.run_sync(_diff) == []
