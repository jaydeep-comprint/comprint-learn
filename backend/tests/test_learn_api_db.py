"""`/learn/*` (spec 004) on a real database with the imported sample content."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, func, select

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.importer import import_tree
from app.models import (
    Attempt,
    Enrollment,
    LessonProgress,
    Misconception,
    SchoolClass,
    StudyTime,
    Subject,
)
from tests.conftest import DbApp
from tests.db_seed import School, seed_school

pytestmark = pytest.mark.db

PHYSICS = "physics-9-10"
MATHS = "maths-9-10"
DIST = f"{PHYSICS}/distance-and-displacement"
SPEED = f"{PHYSICS}/speed-and-velocity"
LIN = f"{MATHS}/linear-equations-two-variables"
LEAKS = {
    "correct",
    "correct_option",
    "explanation",
    "explanation_md",
    "misconception",
    "description",
}


@dataclass
class World:
    a: School
    b: School

    @property
    def maths_student(self) -> uuid.UUID:
        return self.a.student_ids[0]  # 9A maths only

    @property
    def physics_student(self) -> uuid.UUID:
        return self.a.student_ids[3]  # 9B physics only


async def _world(db: DbApp) -> World:
    issues, report = await import_tree(DEFAULT_CONTENT_ROOT, db.sessions)
    assert report is not None, [str(i) for i in issues]
    async with db.sessions() as session:
        a = await seed_school(session, "AAA")
        b = await seed_school(session, "BBB")
    return World(a, b)


def _keys(data: object) -> set[str]:
    if isinstance(data, dict):
        return set(data) | {k for v in data.values() for k in _keys(v)}
    if isinstance(data, list):
        return {k for v in data for k in _keys(v)}
    return set()


def _url(ref: str, tail: str = "") -> str:
    return f"/api/v1/learn/concepts/{ref}{tail}"


async def _get(db: DbApp, user: uuid.UUID, path: str) -> Any:
    r = await db.client.get(path, headers=db.auth(user))
    assert r.status_code == 200, r.text
    return r.json()


async def _post(db: DbApp, user: uuid.UUID, path: str, body: dict[str, Any]) -> Any:
    r = await db.client.post(path, json=body, headers=db.auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def _statuses(outline: dict[str, Any]) -> dict[str, str | None]:
    return {c["id"]: c["status"] for ch in outline["chapters"] for c in ch["concepts"]}


async def _finish(db: DbApp, user: uuid.UUID, ref: str, option: str = "a") -> dict[str, Any]:
    lesson = await _get(db, user, _url(ref))
    await _post(db, user, _url(ref, "/check"), {"option_id": option, "time_taken_ms": 5000})
    out: dict[str, Any] = {}
    for step in lesson["steps"]:
        out = await _post(db, user, _url(ref, "/progress"), {"step": step, "active_seconds": 10})
    assert out["finished_at"] is not None
    return out


async def _count(db: DbApp, model: Any, **where: Any) -> int:
    async with db.sessions() as session:
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return int(await session.scalar(stmt) or 0)


async def test_physics_student_courses_and_outline(db_app: DbApp) -> None:
    w = await _world(db_app)
    courses = await _get(db_app, w.physics_student, "/api/v1/learn/courses")
    assert [c["slug"] for c in courses] == [PHYSICS]
    assert courses[0]["finished"] == 0
    assert courses[0]["total"] == 4  # 3 own + the borrowed maths concept
    assert courses[0]["continue"] == {"id": DIST, "title": "Distance and displacement"}

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
    assert lesson["steps"] == ["intro", "check", "kp:kp1", "kp:kp2", "kp:kp3"]
    assert lesson["progress"] is None and lesson["check_result"] is None
    assert (
        lesson["asset_base"] == "/content-assets/physics-9-10/01-motion/distance-and-displacement/"
    )
    assert lesson["preview"] is False
    assert not (_keys(lesson) & LEAKS), _keys(lesson) & LEAKS
    again = await _get(db_app, s, _url(DIST))
    assert again["check"]["options"] == lesson["check"]["options"]  # stable shuffle

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
        db_app, s, _url(DIST, "/check"), {"option_id": "b", "time_taken_ms": 9_999_999}
    )
    assert result["correct"] is False
    assert result["chosen"] == "b" and result["correct_option"] == "a"
    assert result["misconception"] == {"title": "Displacement is the same as distance"}
    assert "Displacement is a vector" in result["explanation_md"]
    assert result["already_answered"] is False
    assert "description" not in _keys(result)

    again_result = await _post(
        db_app, s, _url(DIST, "/check"), {"option_id": "a", "time_taken_ms": 1}
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
    assert att.response["option"] == "b"
    assert sorted(att.response["order"]) == ["a", "b", "c"]

    # Check answered, kp1 seen: not finished until kp2 and kp3 are seen.
    out = await _post(db_app, s, _url(DIST, "/progress"), {"step": "kp:kp2", "active_seconds": 0})
    assert out["finished_at"] is None
    out = await _post(db_app, s, _url(DIST, "/progress"), {"step": "kp:kp3", "active_seconds": 5})
    assert out["finished_at"] is not None

    reviewed = await _get(db_app, s, _url(DIST))
    assert reviewed["check_result"]["chosen"] == "b"
    assert reviewed["check_result"]["misconception"]["title"]

    async with db_app.sessions() as session:
        seconds = (await session.scalars(select(StudyTime.active_seconds))).all()
    assert sorted(seconds) == [5, 30, 600]  # 3000 clamped, 0 dropped

    # SPEED still needs LIN; finish it from the Physics page.
    outline = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(outline)[SPEED] == "locked"
    await _finish(db_app, s, LIN, "c")
    outline = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(outline)[SPEED] == "ready"


async def test_finish_requires_the_check(db_app: DbApp) -> None:
    w = await _world(db_app)
    s = w.physics_student
    for step in ["intro", "kp:kp1", "kp:kp2", "kp:kp3"]:
        out = await _post(db_app, s, _url(DIST, "/progress"), {"step": step, "active_seconds": 1})
    assert out["finished_at"] is None
    await _post(db_app, s, _url(DIST, "/check"), {"option_id": "a", "time_taken_ms": 100})
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

    await _finish(db_app, s, LIN, "c")  # as a Maths student
    physics = await _get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert _statuses(physics)[LIN] == "finished"
    maths = await _get(db_app, s, f"/api/v1/learn/courses/{MATHS}/outline")
    assert _statuses(maths)[LIN] == "finished"


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
        json={"option_id": "a", "time_taken_ms": 1},
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
    assert [o["id"] for o in dist["check"]["options"]] == ["a", "b", "c"]  # authored order

    result = await _post(db_app, t, _url(DIST, "/check"), {"option_id": "b", "time_taken_ms": 5})
    assert result["correct"] is False and result["misconception"] is not None
    r = await db_app.client.post(
        _url(DIST, "/progress"),
        json={"step": "intro", "active_seconds": 20},
        headers=db_app.auth(t),
    )
    assert r.status_code == 204
    for model in (Attempt, LessonProgress, StudyTime):
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
