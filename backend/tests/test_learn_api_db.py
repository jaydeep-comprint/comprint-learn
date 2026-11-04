"""`/learn/*` (spec 004) on a real database with the imported sample content."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select, text

from app.models import (
    Attempt,
    AttemptContext,
    ConceptState,
    Enrollment,
    KpProgress,
    LessonProgress,
    Misconception,
    PracticeSession,
    Remediation,
    SchoolClass,
    StudyTime,
    Subject,
)
from app.services.learn import learn_attempt_insert
from tests.conftest import DbApp
from tests.learn_helpers import (
    DIST,
    LIN,
    MATHS,
    PHYSICS,
    SPEED,
    count,
    get,
    keys,
    learn_concept,
    post,
    statuses,
    url,
    world,
)

pytestmark = pytest.mark.db

LEAKS = {
    "correct",
    "correct_option",
    "explanation",
    "explanation_md",
    "misconception",
    "description",
}


_world = world
_keys = keys
_url = url
_get = get
_post = post
_statuses = statuses
_count = count


# The correct option's text in each sample check (clients only see positional option ids).
CORRECT = {DIST: "Displacement", LIN: "Infinitely many"}
DIST_AUTHORED = {"Displacement": "a", "Distance": "b", "Both distance and displacement": "c"}


def _opt(lesson: dict[str, Any], text: str) -> str:
    """The client-side id of the option with this text."""
    return str(next(o["id"] for o in lesson["check"]["options"] if o["text"] == text))


async def _finish(db: DbApp, user: uuid.UUID, ref: str) -> dict[str, Any]:
    lesson = await _get(db, user, _url(ref))
    option = _opt(lesson, CORRECT[ref])
    await _post(db, user, _url(ref, "/check"), {"option_id": option, "time_taken_ms": 5000})
    out: dict[str, Any] = {}
    for step in lesson["steps"]:
        out = await _post(db, user, _url(ref, "/progress"), {"step": step, "active_seconds": 10})
    assert out["finished_at"] is not None
    return out


async def test_physics_student_courses_and_outline(db_app: DbApp) -> None:
    w = await _world(db_app)
    courses = await _get(db_app, w.physics_student, "/api/v1/learn/courses")
    assert [c["slug"] for c in courses] == [PHYSICS]
    card = courses[0]
    assert card["learned"] == 0
    assert card["total"] == 4  # 3 own + the borrowed maths concept
    assert "continue" not in card  # no auto-pick: the student chooses
    assert [c["id"] for c in card["ready"]] == [DIST, LIN]
    assert card["ready_count"] == 2
    assert card["in_progress"] == card["waiting"] == card["brush_up"] == []

    outline = await _get(db_app, w.physics_student, f"/api/v1/learn/courses/{PHYSICS}/outline")
    order = list(_statuses(outline))
    assert order.index(LIN) < order.index(SPEED)
    assert order == [DIST, LIN, SPEED, f"{PHYSICS}/acceleration"]
    assert "course" not in _keys(outline["chapters"])  # no "From Maths" label
    statuses = _statuses(outline)
    assert statuses[DIST] == "ready"
    assert statuses[LIN] == "ready"
    assert statuses[SPEED] == "locked"

    r = await db_app.client.get(_url(SPEED), headers=db_app.auth(w.physics_student))
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["code"] == "concept_locked"
    assert {p["id"]: p["status"] for p in body["prereqs"]} == {DIST: "ready", LIN: "ready"}


async def test_staff_get_403_on_student_courses(db_app: DbApp) -> None:
    w = await _world(db_app)
    r = await db_app.client.get("/api/v1/learn/courses", headers=db_app.auth(w.a.teacher_id))
    assert r.status_code == 403


async def test_lesson_flow_check_resume_and_finish(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.physics_student
    lesson = await _get(db_app, s, _url(DIST))
    assert lesson["steps"] == [
        "intro",
        "check",
        "kp:kp1",
        "kpq:kp1",
        "kp:kp2",
        "kpq:kp2",
        "kp:kp3",
        "kpq:kp3",
    ]
    assert lesson["concept_status"] == "ready" and lesson["waiting"] is None
    assert [k["status"] for k in lesson["kps"]] == ["not_started"] * 3
    assert lesson["progress"] is None and lesson["check_result"] is None
    assert (
        lesson["asset_base"] == "/content-assets/physics-9-10/01-motion/distance-and-displacement/"
    )
    assert lesson["preview"] is False
    assert not (_keys(lesson) & LEAKS), _keys(lesson) & LEAKS
    again = await _get(db_app, s, _url(DIST))
    assert again["check"]["options"] == lesson["check"]["options"]  # stable shuffle
    # Positional ids only: authored ids ("a" is usually correct) never reach the client.
    assert [o["id"] for o in lesson["check"]["options"]] == ["1", "2", "3"]
    wrong, right = _opt(lesson, "Distance"), _opt(lesson, "Displacement")

    out = await _post(db_app, s, _url(DIST, "/progress"), {"step": "intro", "active_seconds": 30})
    assert out == {"seen_steps": ["intro"], "last_step": "intro", "finished_at": None}
    out = await _post(
        db_app, s, _url(DIST, "/progress"), {"step": "kp:kp1", "active_seconds": 3000}
    )
    assert out["last_step"] == "kp:kp1"
    resumed = await _get(db_app, s, _url(DIST))
    assert resumed["progress"]["last_step"] == "kp:kp1"

    r = await db_app.client.post(
        _url(DIST, "/check"),
        json={"option_id": "zzz", "time_taken_ms": 1},
        headers=db_app.auth(s),
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_option"
    r = await db_app.client.post(
        _url(DIST, "/progress"),
        json={"step": "kp:nope", "active_seconds": 1},
        headers=db_app.auth(s),
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_step"

    # Wrong, tagged option: misconception title (not description) + explanation.
    result = await _post(
        db_app, s, _url(DIST, "/check"), {"option_id": wrong, "time_taken_ms": 9_999_999}
    )
    assert result["correct"] is False
    assert result["chosen"] == wrong and result["correct_option"] == right
    assert result["misconception"] == {"title": "Displacement is the same as distance"}
    assert "Displacement is a vector" in result["explanation_md"]
    assert result["already_answered"] is False
    assert "description" not in _keys(result)

    again_result = await _post(
        db_app, s, _url(DIST, "/check"), {"option_id": right, "time_taken_ms": 1}
    )
    assert again_result == {**result, "already_answered": True}
    async with db_app.sessions() as session:
        attempts = (await session.scalars(select(Attempt))).all()
        misconception_id = await session.scalar(
            select(Misconception.id).where(Misconception.slug == "displacement-equals-distance")
        )
    assert len(attempts) == 1
    att = attempts[0]
    assert att.item_version == 1 and att.context == "learn" and att.seed is None
    assert att.misconception_id == misconception_id
    assert att.time_taken_ms == 1_800_000 and att.hints_used == 0
    assert att.response["option"] == "b"  # stored as the authored id
    assert att.response["order"] == [DIST_AUTHORED[o["text"]] for o in lesson["check"]["options"]]

    # Check answered, kp1 seen: not finished until kp2 and kp3 are seen.
    out = await _post(db_app, s, _url(DIST, "/progress"), {"step": "kp:kp2", "active_seconds": 0})
    assert out["finished_at"] is None
    out = await _post(db_app, s, _url(DIST, "/progress"), {"step": "kp:kp3", "active_seconds": 5})
    assert out["finished_at"] is not None

    reviewed = await _get(db_app, s, _url(DIST))
    assert reviewed["check_result"]["chosen"] == wrong
    assert reviewed["check_result"]["misconception"]["title"]

    async with db_app.sessions() as session:
        seconds = (await session.scalars(select(StudyTime.active_seconds))).all()
    assert sorted(seconds) == [5, 30, 600]  # 3000 clamped, 0 dropped

    # Spec 005: a "finished" (read) lesson no longer unlocks anything; only learned does.
    outline = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(outline)[DIST] == "in_progress"
    assert _statuses(outline)[SPEED] == "locked"
    await _finish(db_app, s, LIN)
    outline = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(outline)[SPEED] == "locked"
    await learn_concept(db_app, s, DIST)
    await learn_concept(db_app, s, LIN)
    outline = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(outline)[SPEED] == "ready"


async def test_finish_requires_the_check(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.physics_student
    for step in ["intro", "kp:kp1", "kp:kp2", "kp:kp3"]:
        out = await _post(db_app, s, _url(DIST, "/progress"), {"step": step, "active_seconds": 1})
    assert out["finished_at"] is None
    await _post(db_app, s, _url(DIST, "/check"), {"option_id": "1", "time_taken_ms": 100})
    lesson = await _get(db_app, s, _url(DIST))
    assert lesson["progress"]["finished_at"] is not None
    assert "check" in lesson["progress"]["seen_steps"]


async def test_progress_is_shared_across_courses(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.physics_student
    async with db_app.sessions() as session:
        session.add(Enrollment(org_id=w.a.org_id, class_id=w.a.class_ids[0], student_id=s))
        await session.commit()
    courses = await _get(db_app, s, "/api/v1/learn/courses")
    assert [c["slug"] for c in courses] == [MATHS, PHYSICS]

    await learn_concept(db_app, s, LIN)  # as a Maths student
    physics = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(physics)[LIN] == "learned"
    maths = await _get(db_app, s, f"/api/v1/learn/courses/{MATHS}/outline")
    assert _statuses(maths)[LIN] == "learned"


async def test_two_classes_same_subject_one_card_archived_ignored(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.maths_student
    async with db_app.sessions() as session:
        extra = SchoolClass(
            id=uuid.uuid4(),
            org_id=w.a.org_id,
            name="9C maths",
            subject=Subject.maths,
            grade=9,
            created_by=w.a.teacher_id,
        )
        archived = SchoolClass(
            id=uuid.uuid4(),
            org_id=w.a.org_id,
            name="9D python",
            subject=Subject.python,
            grade=9,
            created_by=w.a.teacher_id,
            archived_at=datetime.now(UTC),
        )
        session.add_all([extra, archived])
        await session.flush()
        session.add_all(
            [
                Enrollment(org_id=w.a.org_id, class_id=extra.id, student_id=s),
                Enrollment(org_id=w.a.org_id, class_id=archived.id, student_id=s),
            ]
        )
        await session.commit()
    courses = await _get(db_app, s, "/api/v1/learn/courses")
    assert [c["slug"] for c in courses] == [MATHS]
    r = await db_app.client.get(_url("python-basics/variables-and-types"), headers=db_app.auth(s))
    assert r.status_code == 404


async def test_no_classes_is_empty(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.maths_student
    async with db_app.sessions() as session:
        await session.execute(delete(Enrollment).where(Enrollment.student_id == s))
        await session.commit()
    assert await _get(db_app, s, "/api/v1/learn/courses") == []


async def test_concept_outside_courses_is_404(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.physics_student
    for path in [
        _url(f"{MATHS}/pair-of-linear-equations-graphical"),
        _url("python-basics/variables-and-types"),
        _url(f"{PHYSICS}/nope"),
        f"/api/v1/learn/courses/{MATHS}/outline",
        "/api/v1/learn/courses/nope/outline",
    ]:
        r = await db_app.client.get(path, headers=db_app.auth(s))
        assert r.status_code == 404, (path, r.text)
        assert r.json()["code"] == "not_found"
    r = await db_app.client.post(
        _url("python-basics/variables-and-types", "/check"),
        json={"option_id": "1", "time_taken_ms": 1},
        headers=db_app.auth(s),
    )
    assert r.status_code == 404


async def test_staff_preview_writes_nothing(db_app: DbApp) -> None:
    w = await _world(db_app)
    t = w.a.teacher_id
    outline = await _get(db_app, t, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert set(_statuses(outline).values()) == {None}
    lesson = await _get(db_app, t, _url(SPEED))  # locked for students, open for staff
    assert lesson["preview"] is True and lesson["progress"] is None
    dist = await _get(db_app, t, _url(DIST))
    options = dist["check"]["options"]
    assert [o["text"] for o in options] == list(DIST_AUTHORED)  # authored order
    assert [o["id"] for o in options] == ["1", "2", "3"]

    result = await _post(db_app, t, _url(DIST, "/check"), {"option_id": "2", "time_taken_ms": 5})
    assert result["correct"] is False and result["misconception"] is not None
    r = await db_app.client.post(
        _url(DIST, "/progress"),
        json={"step": "intro", "active_seconds": 20},
        headers=db_app.auth(t),
    )
    assert r.status_code == 204
    for model in (
        Attempt,
        LessonProgress,
        StudyTime,
        ConceptState,
        KpProgress,
        PracticeSession,
        Remediation,
    ):
        assert await _count(db_app, model) == 0, model


async def test_progress_is_per_school(db_app: DbApp) -> None:
    w = await _world(db_app)
    await _finish(db_app, w.physics_student, DIST)
    other = w.b.student_ids[3]  # physics student in school B
    outline = await _get(db_app, other, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(outline)[DIST] == "ready"
    assert _statuses(outline)[SPEED] == "locked"
    lesson = await _get(db_app, other, _url(DIST))
    assert lesson["progress"] is None and lesson["check_result"] is None
    assert await _count(db_app, LessonProgress, org_id=w.b.org_id) == 0


async def test_check_insert_works_under_generic_plans(db_app: DbApp) -> None:
    """Postgres uses generic plans after ~5 runs of a prepared statement; force one now."""
    w = await _world(db_app)
    s = w.physics_student
    lesson = await _get(db_app, s, _url(DIST))
    async with db_app.sessions() as session:
        await session.execute(text("SET plan_cache_mode = force_generic_plan"))
        item_id = uuid.UUID(lesson["check"]["item_id"])
        values: dict[str, Any] = {
            "org_id": w.a.org_id,
            "student_id": s,
            "item_id": item_id,
            "item_version": 1,
            "context": AttemptContext.learn,
            "response": {"option": "a", "order": ["a"]},
            "correct": True,
            "time_taken_ms": 1,
        }
        for _ in range(7):  # first inserts, the rest hit the conflict
            await session.execute(learn_attempt_insert(id=uuid.uuid4(), **values))
        await session.commit()
    assert await _count(db_app, Attempt) == 1


async def test_two_submits_at_once_store_one_attempt(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.physics_student
    lesson = await _get(db_app, s, _url(DIST))
    body = {"option_id": _opt(lesson, "Distance"), "time_taken_ms": 10}
    r1, r2 = await asyncio.gather(
        db_app.client.post(_url(DIST, "/check"), json=body, headers=db_app.auth(s)),
        db_app.client.post(_url(DIST, "/check"), json=body, headers=db_app.auth(s)),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert sorted([r1.json()["already_answered"], r2.json()["already_answered"]]) == [False, True]
    assert await _count(db_app, Attempt) == 1
