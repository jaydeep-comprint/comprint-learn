"""Teacher assignments and the student's Focus Mode against a real database (spec 010)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, update

from app.models import Assignment, Enrollment, SchoolClass
from app.services.kp_flow import IST
from tests import dashboard_seed as ds
from tests.conftest import DbApp
from tests.learn_helpers import ACCEL, DIST, LIN, SPEED, World, world
from tests.review_helpers import seed_learned

pytestmark = pytest.mark.db


def _today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


def _path(w: World, tail: str = "") -> str:
    return f"/api/v1/classes/{w.a.class_ids[1]}/assignments{tail}"


async def _create(db: DbApp, w: World, **body: Any) -> Any:
    payload = {"concepts": [SPEED], "due_date": str(_today() + timedelta(days=3))} | body
    r = await db.client.post(_path(w), json=payload, headers=db.auth(w.a.teacher_id))
    assert r.status_code == 201, r.text
    return r.json()


async def _mine(db: DbApp, sid: uuid.UUID) -> list[dict[str, Any]]:
    r = await db.client.get("/api/v1/me/assignments", headers=db.auth(sid))
    assert r.status_code == 200, r.text
    data: list[dict[str, Any]] = r.json()
    return data


async def test_create_validation_errors(db_app: DbApp) -> None:
    w = await world(db_app)
    today = _today()
    cases: list[tuple[dict[str, Any], int, str]] = [
        ({"concepts": []}, 422, "assignment_invalid"),
        (
            {"concepts": [SPEED] * 2 + [f"physics-9-10/x{i}" for i in range(10)]},
            422,
            "assignment_invalid",
        ),
        ({"concepts": [LIN]}, 422, "concept_not_in_course"),
        ({"due_date": str(today - timedelta(days=2))}, 422, "assignment_invalid"),
        ({"due_date": str(today + timedelta(days=200))}, 422, "assignment_invalid"),
        ({"note": "x" * 201}, 422, "assignment_invalid"),
        ({"student_ids": [str(w.maths_student)]}, 422, "students_not_in_class"),
        ({"student_ids": []}, 422, "students_not_in_class"),
    ]
    for override, status, code in cases:
        payload = {"concepts": [SPEED], "due_date": str(today + timedelta(days=3))} | override
        r = await db_app.client.post(_path(w), json=payload, headers=db_app.auth(w.a.teacher_id))
        assert (r.status_code, r.json().get("code")) == (status, code), override
    # Duplicates are de-duplicated; the note is trimmed.
    made = await _create(db_app, w, concepts=[SPEED, SPEED, DIST], note="  revise  ")
    assert [c["concept"] for c in made["concepts"]] == [SPEED, DIST]
    assert made["note"] == "revise" and made["title"].endswith("+ 1 more")
    # Another school's class is 404; a student is 403.
    other = f"/api/v1/classes/{w.b.class_ids[1]}/assignments"
    r = await db_app.client.get(other, headers=db_app.auth(w.a.teacher_id))
    assert r.status_code == 404
    r = await db_app.client.get(_path(w), headers=db_app.auth(w.physics_student))
    assert r.status_code == 403
    r = await db_app.client.get("/api/v1/me/assignments", headers=db_app.auth(w.a.teacher_id))
    assert r.status_code == 403


async def test_archived_class_is_read_only(db_app: DbApp) -> None:
    w = await world(db_app)
    made = await _create(db_app, w)
    async with db_app.sessions() as session:
        await session.execute(
            update(SchoolClass)
            .where(SchoolClass.id == w.a.class_ids[1])
            .values(archived_at=datetime.now(UTC))
        )
        await session.commit()
    auth = db_app.auth(w.a.teacher_id)
    r = await db_app.client.post(
        _path(w), json={"concepts": [SPEED], "due_date": str(_today())}, headers=auth
    )
    assert (r.status_code, r.json()["code"]) == (409, "class_archived")
    r = await db_app.client.patch(_path(w, f"/{made['id']}"), json={"note": "x"}, headers=auth)
    assert r.status_code == 409
    r = await db_app.client.delete(_path(w, f"/{made['id']}"), headers=auth)
    assert r.status_code == 409
    r = await db_app.client.get(_path(w), headers=auth)
    assert r.status_code == 200 and len(r.json()) == 1
    # Hidden from students.
    assert await _mine(db_app, w.physics_student) == []


async def test_patch_and_delete(db_app: DbApp) -> None:
    w = await world(db_app)
    s3 = w.a.student_ids[3]
    made = await _create(db_app, w, student_ids=[str(s3)])
    assert made["all_students"] is False and made["counts"]["total"] == 1
    auth = db_app.auth(w.a.teacher_id)
    # Make the due date past via the DB: an unchanged past date still saves on PATCH.
    async with db_app.sessions() as session:
        await session.execute(
            update(Assignment)
            .where(Assignment.id == uuid.UUID(made["id"]))
            .values(due_date=_today() - timedelta(days=2))
        )
        await session.commit()
    r = await db_app.client.patch(
        _path(w, f"/{made['id']}"),
        json={"due_date": str(_today() - timedelta(days=2)), "student_ids": None},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["all_students"] is True and data["counts"]["total"] == 3
    assert data["counts"]["overdue"] == 3 and data["active"] is False
    r = await db_app.client.patch(
        _path(w, f"/{made['id']}"), json={"concepts": [ACCEL], "note": " "}, headers=auth
    )
    assert r.json()["concepts"][0]["concept"] == ACCEL and r.json()["note"] is None
    # The roster flags overdue students.
    roster = (
        await db_app.client.get(f"/api/v1/classes/{w.a.class_ids[1]}/students", headers=auth)
    ).json()
    assert all("overdue_assignment" in row["at_risk"] for row in roster)
    detail = (await db_app.client.get(_path(w, f"/{made['id']}"), headers=auth)).json()
    assert {s["status"] for s in detail["students"]} == {"overdue"}
    r = await db_app.client.delete(_path(w, f"/{made['id']}"), headers=auth)
    assert r.status_code == 204
    assert (await db_app.client.get(_path(w), headers=auth)).json() == []
    r = await db_app.client.get(_path(w, f"/{made['id']}"), headers=auth)
    assert r.status_code == 404


async def test_focus_mode_audience_path_and_next(db_app: DbApp) -> None:
    w = await world(db_app)
    s3, s4, s5 = w.a.student_ids[3:6]
    whole = await _create(db_app, w, concepts=[ACCEL], note="Before the test")
    chosen = await _create(db_app, w, concepts=[DIST], student_ids=[str(s4)])

    mine = await _mine(db_app, s3)
    assert [m["id"] for m in mine] == [whole["id"]]
    [card] = mine
    assert card["status"] == "not_started" and card["note"] == "Before the test"
    # The path: unlearned ancestors first (incl. the cross-course Lin), then the target.
    path = [p["concept"] for p in card["path"]]
    assert path[-1] == ACCEL and path.index(DIST) < path.index(SPEED)
    assert LIN in path
    assert card["next"]["concept"] in (DIST, LIN)  # the first ready step
    assert {m["id"] for m in await _mine(db_app, s4)} == {whole["id"], chosen["id"]}

    # A student enrolled later gets the whole-class assignment.
    async with db_app.sessions() as session:
        [late] = await ds.add_students(session, w.a.org_id, w.a.class_ids[1], 1, "late")
        await session.commit()
    assert [m["id"] for m in await _mine(db_app, late)] == [whole["id"]]
    # A removed student loses it.
    async with db_app.sessions() as session:
        await session.execute(delete(Enrollment).where(Enrollment.student_id == s5))
        await session.commit()
    assert await _mine(db_app, s5) == []


async def test_focus_mode_done_filters_and_order(db_app: DbApp) -> None:
    w = await world(db_app)
    s3 = w.a.student_ids[3]
    # Already learned before the assignment exists: done early, hidden from the student.
    await seed_learned(db_app, w.a.org_id, s3, [DIST], days_ago=1)
    early = await _create(db_app, w, concepts=[DIST])
    soon = await _create(db_app, w, concepts=[SPEED], due_date=str(_today() + timedelta(days=5)))
    late = await _create(db_app, w, concepts=[ACCEL], due_date=str(_today() + timedelta(days=1)))
    async with db_app.sessions() as session:
        await session.execute(
            update(Assignment)
            .where(Assignment.id == uuid.UUID(late["id"]))
            .values(due_date=_today() - timedelta(days=1))
        )
        await session.commit()
    mine = await _mine(db_app, s3)
    assert [m["id"] for m in mine] == [late["id"], soon["id"]]  # overdue first
    assert mine[0]["status"] == "overdue"
    detail = (
        await db_app.client.get(_path(w, f"/{early['id']}"), headers=db_app.auth(w.a.teacher_id))
    ).json()
    s3_row = next(s for s in detail["students"] if s["student_id"] == str(s3))
    assert s3_row["status"] == "done_early"
    assert detail["counts"]["already_learned"] == 1 and detail["counts"]["done"] == 1

    # Done on time, then more than 7 days later: hidden.
    async with db_app.sessions() as session:
        await session.execute(
            update(Assignment)
            .where(Assignment.id == uuid.UUID(early["id"]))
            .values(created_at=datetime.now(UTC) - timedelta(days=20))
        )
        await session.commit()
    by_id = {m["id"]: m for m in await _mine(db_app, s3)}
    assert by_id[early["id"]]["status"] == "done_on_time" and by_id[early["id"]]["path"] == []
    await seed_learned(db_app, w.a.org_id, w.a.student_ids[4], [DIST], days_ago=9)
    assert early["id"] not in {m["id"] for m in await _mine(db_app, w.a.student_ids[4])}

    # A deleted assignment disappears.
    await db_app.client.delete(_path(w, f"/{soon['id']}"), headers=db_app.auth(w.a.teacher_id))
    assert soon["id"] not in {m["id"] for m in await _mine(db_app, s3)}
