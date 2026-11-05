"""Teacher AI summaries against a real database (spec 011), on spec 010's seeded physics class:
facts match the dashboard, names render on read, caps / cooldown / busy / archived / kill switch,
privacy of what the model sees, scope, and a fixed query count."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from app.ai import teacher_facts as tf
from app.ai import teacher_limits as lim
from app.ai.teacher_client import TeacherAIUnavailable
from app.api.deps import CurrentUser, OrgScope
from app.core.config import get_settings
from app.models import (
    AppUser,
    ConceptStatus,
    Enrollment,
    Role,
    SchoolClass,
    TeacherSummary,
    TeacherSummaryKind,
    TeacherSummaryStatus,
)
from app.schemas.dashboard import Window
from app.services import class_view, kp_flow, teacher_ai
from tests import dashboard_seed as ds
from tests.conftest import DbApp
from tests.learn_helpers import SPEED
from tests.query_count import count_queries
from tests.test_dashboard_db import Seed, _seed

pytestmark = pytest.mark.db

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _summary(s: Seed, student: uuid.UUID | None = None, window: str = "7d") -> str:
    if student is not None:
        return s.path(f"/students/{student}/summary")
    return s.path(f"/summary?window={window}")


async def _get(db: DbApp, s: Seed, path: str, user: uuid.UUID | None = None) -> Any:
    r = await db.client.get(path, headers=db.auth(user or s.teacher))
    assert r.status_code == 200, r.text
    return r.json()


async def _post(db: DbApp, s: Seed, path: str, user: uuid.UUID | None = None) -> Any:
    return await db.client.post(path, headers=db.auth(user or s.teacher))


async def _class_facts(db: DbApp, s: Seed, window: Window = "7d") -> tf.FactSet:
    async with db.sessions() as session:
        scope = OrgScope(session, CurrentUser(s.teacher, s.org, Role.teacher, False, False))
        ctx = await class_view.load(scope, s.cls)
        return tf.class_facts(await teacher_ai.class_input(scope, ctx, window))


def _fact(fs: tf.FactSet, kind: str) -> tf.Fact:
    return next(f for f in fs.facts if f.kind == kind)


async def _names(db: DbApp) -> list[str]:
    async with db.sessions() as session:
        rows = (await session.execute(select(AppUser.display_name, AppUser.username))).all()
    return [v for row in rows for v in row if v and len(v) > 2]


async def _rows(db: DbApp, s: Seed) -> list[TeacherSummary]:
    async with db.sessions() as session:
        result = await session.scalars(
            select(TeacherSummary)
            .where(TeacherSummary.org_id == s.org)
            .order_by(TeacherSummary.created_at)
        )
        return list(result.all())


async def test_facts_match_the_dashboard(db_app: DbApp) -> None:
    s = await _seed(db_app)
    overview = await _get(db_app, s, s.path("/overview"))
    fs = await _class_facts(db_app, s)
    [speed] = overview["weakest"]
    weak = _fact(fs, "weak_concept")
    assert f"4 of {speed['tries']} KP tries failed (67%)" in weak.text
    assert f"by {speed['students_tried']} students; {speed['stuck_now']} stuck now" in weak.text
    assert f"{speed['learned_pct']}% learned (last 7 days)" in weak.text
    assert _fact(fs, "class").text.startswith(f"{overview['students_in_scope']} students")
    [m] = overview["misconceptions"]
    misc = _fact(fs, "misconception")
    assert f"chosen in {m['chosen']} of {m['offered']} answers" in misc.text
    assert len(misc.students) == m["students"]
    assert sum(f.kind == "at_risk" for f in fs.facts) == len(overview["at_risk"])
    # Causes: s3's open review of Distance, and the remediation created in the window.
    now = _fact(fs, "cause_now")
    assert f"Prerequisite '{s.dist_title}' is the open cause for 1 students" in now.text
    assert now.text.endswith("1 brushing up.")
    window = _fact(fs, "cause_window")
    assert f"sent 1 students to prerequisite '{s.dist_title}'" in window.text
    assert "0 have resolved it" in window.text
    assert tf.enough_data(fs)


async def test_generate_store_and_render(db_app: DbApp) -> None:
    s = await _seed(db_app)
    state = await _get(db_app, s, _summary(s))
    assert state["enabled"] and state["enough_data"] and state["summary"] is None
    assert state["can_regenerate"] and state["blocked"] is None
    assert state["daily_left"] == lim.TEACHER_DAILY_CAP
    assert db_app.teacher_ai.requests == []  # GET never calls the model

    fs = await _class_facts(db_app, s)
    cause = _fact(fs, "cause_now")
    s3 = next(p for p, sid in fs.pseudonyms.items() if sid == s.s3)
    db_app.teacher_ai.queue(
        {
            "summary": [
                {"text": f"{{{s3}}} is stuck on Speed.", "facts": [cause.id]},
                {"text": "Speed is the weakest concept.", "facts": [_fact(fs, "weak_concept").id]},
            ],
            "notes": [
                {
                    "focus": "Speed: revisit Distance first",
                    "why": {"text": "Distance is the open cause.", "facts": [cause.id]},
                    "revisit": [r.id for r in fs.resources[:2]],
                    "group": [s3],
                    "group_facts": [cause.id],
                }
            ],
        }
    )
    r = await _post(db_app, s, _summary(s))
    assert r.status_code == 201, r.text
    body = r.json()
    async with db_app.sessions() as session:
        s3_name = str(await session.scalar(select(AppUser.display_name).where(AppUser.id == s.s3)))
    assert body["status"] == "ok"
    assert body["claims"][0]["text"] == f"{s3_name} is stuck on Speed."
    assert body["claims"][0]["citations"] == [cause.id]
    assert {f["id"] for f in body["facts"]} == {cause.id, _fact(fs, "weak_concept").id}
    linked = next(f for f in body["facts"] if f["id"] == cause.id)
    assert linked["link"] == {
        "kind": "concept",
        "concept": SPEED,
        "id": None,
        "student_id": None,
        "card": None,
        "section": None,
    }
    [note] = body["notes"]
    assert note["group"] == [{"student_id": str(s.s3), "display_name": s3_name}]
    assert note["assign"]["student_ids"] == [str(s.s3)]
    assert SPEED in note["assign"]["concepts"]
    assert all(r["available"] for r in note["revisit"])

    # Privacy: what the model saw holds no names, usernames, ids or emails.
    prompt = db_app.teacher_ai.prompt_text()
    for name in await _names(db_app):
        assert name not in prompt, name
    assert not UUID_RE.search(prompt)
    assert "@" not in prompt
    request = db_app.teacher_ai.requests[0]
    assert request["model"] == get_settings().teacher_ai_model
    assert request["response_format"] == {"type": "json_object"}

    [row] = await _rows(db_app, s)
    assert row.status == TeacherSummaryStatus.ok and row.calls == 1
    assert (row.input_tokens, row.cache_read_tokens, row.output_tokens) == (1200, 800, 300)
    assert row.model == "fake-v4-pro"
    assert row.pseudonyms[s3] == str(s.s3)
    assert s3_name not in str(row.facts) and s3_name not in str(row.content)

    # Shared with the school's teachers; fresh, so regenerating is blocked.
    state = await _get(db_app, s, _summary(s), user=s.w.a.admin_id)
    assert state["summary"]["id"] == str(row.id)
    assert state["summary"]["created_by_name"]
    assert not state["stale"] and state["blocked"] == "fresh"
    r = await _post(db_app, s, _summary(s))
    assert (r.status_code, r.json()["code"]) == (409, "summary_fresh")

    # A new KP try changes the facts: stale, and regenerating works.
    async with db_app.sessions() as session:
        kp1 = (await ds.kps_of(session, s.speed))[0]
        await ds.kp_try(session, s.org, s.s5, kp1, passed=False)
        await session.commit()
    state = await _get(db_app, s, _summary(s))
    assert state["stale"] and state["can_regenerate"]
    assert (await _post(db_app, s, _summary(s))).status_code == 201

    # Unenrolled: the name is replaced, the group and prefill drop the student.
    async with db_app.sessions() as session:
        await session.execute(
            delete(Enrollment).where(Enrollment.class_id == s.cls, Enrollment.student_id == s.s3)
        )
        await session.commit()
    async with db_app.sessions() as session:
        await session.execute(
            update(TeacherSummary)
            .where(TeacherSummary.id != row.id)
            .values(status=TeacherSummaryStatus.error)
        )
        await session.commit()
    state = await _get(db_app, s, _summary(s))
    summary = state["summary"]
    assert summary["claims"][0]["text"] == "a student no longer in this class is stuck on Speed."
    assert summary["notes"][0]["group"] == []
    assert summary["notes"][0]["assign"]["student_ids"] == []


async def test_retry_partial_and_failed(db_app: DbApp) -> None:
    s = await _seed(db_app)
    fs = await _class_facts(db_app, s)
    weak = _fact(fs, "weak_concept").id
    bad = {"summary": [{"text": "99 students failed.", "facts": [weak]}]}
    db_app.teacher_ai.queue(bad, bad)
    r = await _post(db_app, s, _summary(s))
    assert (r.status_code, r.json()["code"]) == (502, "summary_failed")
    assert len(db_app.teacher_ai.requests) == 2
    retry = db_app.teacher_ai.requests[1]["messages"][-1]
    assert retry["role"] == "system" and "number 99" in retry["content"]

    good = {"text": "Speed is the weakest concept.", "facts": [weak]}
    db_app.teacher_ai.queue({"summary": [good, {"text": "99 failed.", "facts": [weak]}]})
    r = await _post(db_app, s, _summary(s))
    assert r.status_code == 201 and r.json()["status"] == "partial"
    statuses = [row.status for row in await _rows(db_app, s)]
    assert statuses == [TeacherSummaryStatus.failed, TeacherSummaryStatus.partial]
    state = await _get(db_app, s, _summary(s))
    assert state["daily_left"] == lim.TEACHER_DAILY_CAP - 2  # a failed row counts


async def test_provider_error_is_not_counted(db_app: DbApp) -> None:
    s = await _seed(db_app)
    db_app.teacher_ai.queue(TeacherAIUnavailable("timeout"))
    r = await _post(db_app, s, _summary(s))
    assert (r.status_code, r.json()["code"]) == (503, "teacher_ai_unavailable")
    [row] = await _rows(db_app, s)
    assert row.status == TeacherSummaryStatus.error
    state = await _get(db_app, s, _summary(s))
    assert state["daily_left"] == lim.TEACHER_DAILY_CAP and state["can_regenerate"]


def _row(s: Seed, created_by: uuid.UUID, status: TeacherSummaryStatus, **kw: Any) -> TeacherSummary:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "org_id": s.org,
        "class_id": s.cls,
        "kind": TeacherSummaryKind.class_,
        "window": "30d",
        "status": status,
        "facts": {"kind": "class", "window": "30d", "facts": [], "resources": []},
        "pseudonyms": {},
        "facts_hash": "x",
        "created_by": created_by,
        "day": now.astimezone(kp_flow.IST).date(),
    }
    values.update(kw)
    return TeacherSummary(**values)


async def test_caps(db_app: DbApp) -> None:
    s = await _seed(db_app)
    async with db_app.sessions() as session:
        for _ in range(lim.TEACHER_DAILY_CAP):
            session.add(_row(s, s.teacher, TeacherSummaryStatus.ok))
        await session.commit()
    state = await _get(db_app, s, _summary(s))
    assert state["blocked"] == "teacher_cap" and state["daily_left"] == 0
    r = await _post(db_app, s, _summary(s))
    body = r.json()
    assert (r.status_code, body["code"]) == (429, "teacher_ai_daily_cap")
    assert body["resets_at"]
    assert db_app.teacher_ai.requests == []

    # Another teacher of the school can still generate, until the school cap.
    other = s.w.a.admin_id
    assert (await _post(db_app, s, _summary(s), user=other)).status_code == 201
    async with db_app.sessions() as session:
        for _ in range(lim.SCHOOL_DAILY_CAP):  # the first teacher's: `other` stays under its cap
            session.add(_row(s, s.teacher, TeacherSummaryStatus.failed))
        await session.commit()
    r = await _post(db_app, s, _summary(s, window="all"), user=other)
    assert (r.status_code, r.json()["code"]) == (429, "school_ai_daily_cap")


async def test_busy_and_stale_pending(db_app: DbApp) -> None:
    s = await _seed(db_app)
    async with db_app.sessions() as session:
        session.add(_row(s, s.w.a.admin_id, TeacherSummaryStatus.pending, window="7d"))
        await session.commit()
    state = await _get(db_app, s, _summary(s))
    assert state["blocked"] == "busy"
    r = await _post(db_app, s, _summary(s))
    assert (r.status_code, r.json()["code"]) == (409, "summary_busy")

    old = datetime.now(UTC) - lim.STALE_PENDING - timedelta(minutes=1)
    async with db_app.sessions() as session:
        await session.execute(update(TeacherSummary).values(created_at=old))
        await session.commit()
    assert (await _post(db_app, s, _summary(s))).status_code == 201
    first = (await _rows(db_app, s))[0]
    assert first.status == TeacherSummaryStatus.error


async def test_archived_not_enough_data_and_kill_switch(
    db_app: DbApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _seed(db_app)
    maths = s.w.a.class_ids[0]  # no activity yet
    state = await _get(db_app, s, f"/api/v1/classes/{maths}/summary")
    assert state["enabled"] and not state["enough_data"]
    assert state["blocked"] == "not_enough_data"
    r = await _post(db_app, s, f"/api/v1/classes/{maths}/summary")
    assert (r.status_code, r.json()["code"]) == (422, "not_enough_data")
    assert db_app.teacher_ai.requests == []
    assert await _rows(db_app, s) == []

    async with db_app.sessions() as session:
        await session.execute(
            update(SchoolClass).where(SchoolClass.id == s.cls).values(archived_at=datetime.now(UTC))
        )
        await session.commit()
    assert (await _get(db_app, s, _summary(s)))["blocked"] == "archived"
    r = await _post(db_app, s, _summary(s))
    assert (r.status_code, r.json()["code"]) == (409, "class_archived")

    monkeypatch.setenv("TEACHER_AI_ENABLED", "false")
    get_settings.cache_clear()
    state = await _get(db_app, s, _summary(s))
    assert state["enabled"] is False
    r = await _post(db_app, s, _summary(s))
    assert (r.status_code, r.json()["code"]) == (503, "teacher_ai_unavailable")


async def test_student_summary_and_scope(db_app: DbApp) -> None:
    s = await _seed(db_app)
    state = await _get(db_app, s, _summary(s, s.s3))
    assert state["enabled"] and state["enough_data"]
    r = await _post(db_app, s, _summary(s, s.s3))
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "student"
    prompt = db_app.teacher_ai.prompt_text()
    assert "STUDENT SUMMARY for {S1}" in prompt
    assert "{S2}" not in prompt  # only the student, as S1
    for name in await _names(db_app):
        assert name not in prompt, name
    [row] = await _rows(db_app, s)
    assert row.kind == TeacherSummaryKind.student and row.pseudonyms == {"S1": str(s.s3)}

    # A deactivated but enrolled student can be summarised.
    assert (await _get(db_app, s, _summary(s, s.gone)))["enabled"]

    for sid in (s.w.maths_student, s.w.b.student_ids[3], uuid.uuid4()):
        for method in ("get", "post"):
            r = await getattr(db_app.client, method)(
                _summary(s, sid), headers=db_app.auth(s.teacher)
            )
            assert r.status_code == 404, (sid, method)
    r = await db_app.client.get(_summary(s), headers=db_app.auth(s.w.b.teacher_id))
    assert r.status_code == 404  # another school's class
    r = await db_app.client.get(_summary(s), headers=db_app.auth(s.s3))
    assert r.status_code == 403  # students never see summaries


async def _count(db: DbApp, s: Seed) -> tuple[int, int]:
    with count_queries() as c:
        await _get(db, s, _summary(s))
    with count_queries() as d:
        await _get(db, s, _summary(s, s.s3))
    return c.n, d.n


async def test_fixed_query_count_for_get_summary(db_app: DbApp) -> None:
    s = await _seed(db_app)
    assert (await _post(db_app, s, _summary(s))).status_code == 201
    small = await _count(db_app, s)
    async with db_app.sessions() as session:
        kp1 = (await ds.kps_of(session, s.speed))[0]
        extra = await ds.add_students(session, s.org, s.cls, 36, "bulk")
        for sid in extra:
            await ds.kp_try(session, s.org, sid, kp1, passed=False)
            session.add(ds.concept_state(s.org, sid, s.speed, ConceptStatus.in_progress))
        await session.commit()
    assert await _count(db_app, s) == small
