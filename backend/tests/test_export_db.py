"""Right of access (spec 014): the student export has every section, only that student's rows,
no answer keys, a fixed query count, admin-only access and an audit event."""

import json
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text

from app.api.deps import CurrentUser, OrgScope
from app.models import (
    AuditAction,
    AuditEvent,
    Item,
    Role,
    TeacherSummary,
    TeacherSummaryKind,
    TeacherSummaryStatus,
)
from app.services import export
from tests.conftest import DbApp
from tests.db_seed import grant_consent
from tests.learn_helpers import SPEED, World, world
from tests.query_count import count_queries
from tests.test_tutor_api_db import answer, call, kp1_question, tutor_url

pytestmark = pytest.mark.db

SECTIONS = {
    "export_version",
    "generated_at",
    "student",
    "school",
    "consent",
    "classes",
    "concepts",
    "attempts",
    "study_time",
    "practice_sessions",
    "remediations",
    "xp_events",
    "xp_days",
    "goals",
    "review_cards",
    "review_log",
    "quizzes",
    "diagnostics",
    "assignments",
    "tutor",
    "ai_summaries",
}
FORBIDDEN_KEYS = {"answer", "explanation", "solution", "hidden", "facts", "pseudonyms"}


def leaves(data: Any) -> tuple[set[str], set[str]]:
    """(every key, every string value) in a JSON document."""
    keys: set[str] = set()
    values: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                keys.add(k)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            values.add(x)

    walk(data)
    return keys, values


async def seed(db: DbApp) -> tuple[World, uuid.UUID, uuid.UUID]:
    """A physics student with a lesson, a KP answer, a hint and a chat, an assignment and a
    per-student AI summary; a classmate with their own rows."""
    w = await world(db)
    async with db.sessions() as session:
        await grant_consent(session, w.a)
    s, other = w.a.student_ids[3], w.a.student_ids[4]
    for student in (s, other):
        q = await kp1_question(db, student)
        code, _ = await call(db, student, "POST", tutor_url(q, "/hint"))
        assert code == 200
        code, _ = await call(db, student, "POST", tutor_url(q, "/messages"), text="why so?")
        assert code == 200
        await answer(db, student, q, correct=True)
    r = await db.client.post(
        f"/api/v1/classes/{w.a.class_ids[1]}/assignments",
        json={"concepts": [SPEED], "due_date": str(date.today() + timedelta(days=3))},
        headers=db.auth(w.a.teacher_id),
    )
    assert r.status_code in (200, 201), r.text
    async with db.sessions() as session:
        session.add(
            TeacherSummary(
                org_id=w.a.org_id,
                class_id=w.a.class_ids[1],
                student_id=s,
                kind=TeacherSummaryKind.student,
                window="7d",
                status=TeacherSummaryStatus.ok,
                facts={"secret": "facts"},
                pseudonyms={"S1": str(s), "S2": str(other)},
                facts_hash="x",
                content={"summary": [{"text": "{S1} is ahead of {S2}.", "cites": [1]}]},
                created_by=w.a.teacher_id,
                day=date.today(),
            )
        )
        await session.commit()
    return w, s, other


async def test_export_has_every_section_and_only_that_student(db_app: DbApp) -> None:
    w, s, other = await seed(db_app)
    r = await db_app.client.get(f"/api/v1/students/{s}/export", headers=db_app.auth(w.a.admin_id))
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith('attachment; filename="student-aaa10-')
    data = r.json()
    assert set(data) == SECTIONS and data["export_version"] == 1
    assert data["student"]["username"] == "aaa10" and data["school"]["code"] == "AAA"
    assert [c["name"] for c in data["classes"]] == ["9B physics"]
    for section in (
        "concepts",
        "attempts",
        "study_time",
        "practice_sessions",
        "xp_events",
        "tutor",
    ):
        assert data[section], section
    concept = next(
        c for c in data["concepts"] if c["concept"].endswith("distance-and-displacement")
    )
    assert concept["title"] and concept["lesson"] and concept["kps"]
    assert data["attempts"][0]["item"].startswith("physics")  # a slug path, not an id
    assert data["consent"]["tutor_consent_form"] and data["consent"]["events"] == []
    msgs = [m for t in data["tutor"] for m in t["messages"]]
    assert {m["text"] for m in msgs} >= {"why so?"}
    assert not {"input_tokens", "latency_ms", "model"} & set(msgs[0])
    [assignment] = data["assignments"]
    assert assignment["concepts"] == [SPEED] and assignment["status"] == "not_started"
    [summary] = data["ai_summaries"]
    assert summary["content"]["summary"][0]["text"] == "Aaa10 is ahead of {S2}."

    keys, values = leaves(data)
    assert not keys & FORBIDDEN_KEYS
    async with db_app.sessions() as session:
        usernames = (
            await session.scalars(text("SELECT username FROM app_user WHERE id <> :s"), {"s": s})
        ).all()
        answered = {a["item"].split("/")[-1] for a in data["attempts"]}
        answers = (await session.scalars(select(Item.answer).where(Item.slug.in_(answered)))).all()
    assert str(other) not in json.dumps(data)
    assert not values & {u for u in usernames if u}
    explanations: set[str] = set()
    for a in answers:
        _, vals = leaves({k: v for k, v in a.items() if k in ("explanation", "solution")})
        explanations |= {v for v in vals if len(v) > 8}
    assert explanations and not values & explanations

    async with db_app.sessions() as session:
        [event] = (await session.scalars(select(AuditEvent))).all()
    assert (event.action, event.target_id, event.actor_id, event.meta) == (
        AuditAction.export_downloaded,
        s,
        w.a.admin_id,
        {"source": "ui"},
    )


async def test_export_is_admin_only_and_404s_for_erased(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.a.student_ids[0]
    r = await db_app.client.get(f"/api/v1/students/{s}/export", headers=db_app.auth(w.a.teacher_id))
    assert r.status_code == 403
    r = await db_app.client.get(
        f"/api/v1/students/{w.a.teacher_id}/export", headers=db_app.auth(w.a.admin_id)
    )
    assert r.status_code == 404
    async with db_app.sessions() as session:
        await session.execute(
            text("UPDATE app_user SET status = 'erased', erased_at = now() WHERE id = :s"),
            {"s": s},
        )
        await session.commit()
    r = await db_app.client.get(f"/api/v1/students/{s}/export", headers=db_app.auth(w.a.admin_id))
    assert r.status_code == 404


async def test_query_count_does_not_grow_with_rows(db_app: DbApp) -> None:
    w, s, _ = await seed(db_app)

    async def queries() -> int:
        async with db_app.sessions() as session:
            scope = OrgScope(
                session, CurrentUser(w.a.admin_id, w.a.org_id, Role.teacher, True, False)
            )
            with count_queries() as c:
                await export.student_export(scope, s)
            return c.n

    one = await queries()
    async with db_app.sessions() as session:
        await session.execute(
            text(
                "INSERT INTO attempt (id, org_id, student_id, item_id, item_version, context, "
                "response, correct, time_taken_ms, session_id, position, step) "
                "SELECT gen_random_uuid(), org_id, student_id, item_id, item_version, context, "
                "response, correct, time_taken_ms, session_id, 1000 + g, step "
                "FROM attempt, generate_series(1, 500) g WHERE student_id = :s AND context = 'kp' "
                "AND step = 0 LIMIT 500"
            ),
            {"s": s},
        )
        await session.commit()
        n = await session.scalar(
            text("SELECT count(*) FROM attempt WHERE student_id = :s"), {"s": s}
        )
    assert n is not None and n > 500
    assert await queries() == one
