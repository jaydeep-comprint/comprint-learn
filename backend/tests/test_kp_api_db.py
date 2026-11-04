"""KP questions, pass/fail, reopening and remediation (spec 005) on a real database."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.models import (
    Attempt,
    ConceptState,
    ConceptStatus,
    Enrollment,
    KnowledgePoint,
    KpProgress,
    KpStatus,
    LessonProgress,
    PracticeSession,
    Remediation,
    RemediationState,
    StudyTime,
)
from app.services.kp_flow import next_midnight_ist
from tests.conftest import DbApp
from tests.learn_helpers import (
    ACCEL,
    DIST,
    LIN,
    MATHS,
    PHYSICS,
    SPEED,
    answer_check,
    answer_kp,
    count,
    get,
    keys,
    learn_concept,
    post,
    response_for,
    statuses,
    url,
    world,
)

pytestmark = pytest.mark.db

LIN_SLUG = LIN.split("/")[1]
LEAKS = {"answer", "params", "solution", "spec", "explanation", "explanation_md", "display_answer"}


def q_url(ref: str, kp: str) -> str:
    return url(ref, f"/kps/{kp}/question")


def a_url(ref: str, kp: str) -> str:
    return url(ref, f"/kps/{kp}/answer")


async def _status(db: DbApp, user: uuid.UUID, path: str) -> tuple[int, Any]:
    r = await db.client.get(path, headers=db.auth(user))
    return r.status_code, r.json()


async def _kp_row(db: DbApp, user: uuid.UUID, concept_slug: str, kp: str) -> KpProgress | None:
    async with db.sessions() as session:
        return await session.scalar(
            select(KpProgress)
            .join(KnowledgePoint, KnowledgePoint.id == KpProgress.kp_id)
            .where(KpProgress.student_id == user, KnowledgePoint.slug == kp)
            .where(KnowledgePoint.concept_id.in_(_concept_ids(concept_slug)))
        )


def _concept_ids(slug: str) -> Any:
    from app.models import Concept

    return select(Concept.id).where(Concept.slug == slug)


async def _cooldown_over(db: DbApp, user: uuid.UUID) -> None:
    async with db.sessions() as session:
        await session.execute(
            update(KpProgress)
            .where(KpProgress.student_id == user, KpProgress.status == KpStatus.failed)
            .values(reopen_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def _open_lesson(db: DbApp, user: uuid.UUID, ref: str) -> None:
    await post(db, user, url(ref, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db, user, ref)


async def test_check_first_then_kp_order(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    code, body = await _status(db_app, s, q_url(DIST, "kp1"))
    assert code == 409 and body["code"] == "check_first"
    await _open_lesson(db_app, s, DIST)
    code, body = await _status(db_app, s, q_url(DIST, "kp2"))
    assert code == 409 and body["code"] == "kp_order"
    code, body = await _status(db_app, s, q_url(DIST, "nope"))
    assert code == 404


async def test_pass_a_kp_same_question_on_reload_no_leaks(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    q = await get(db_app, s, q_url(DIST, "kp1"))
    assert not (keys(q) & LEAKS), keys(q) & LEAKS
    assert q["position"] == 1 and q["results"] == [] and q["preview_seed"] is None
    assert "{{" not in q["prompt_md"]
    again = await get(db_app, s, q_url(DIST, "kp1"))
    assert again == q  # same item, seed (prompt) and position: no re-rolling by reloading

    first = await post(
        db_app,
        s,
        a_url(DIST, "kp1"),
        {"position": 1, "response": await response_for(db_app, q), "time_taken_ms": 4000},
    )
    assert first["correct"] is True and first["session_status"] == "active"
    assert first["results"] == [True]
    q2 = await get(db_app, s, q_url(DIST, "kp1"))
    assert q2["position"] == 2 and q2["item_id"] != q["item_id"]  # never repeats in a session
    second = await post(
        db_app,
        s,
        a_url(DIST, "kp1"),
        {"position": 2, "response": await response_for(db_app, q2), "time_taken_ms": 4000},
    )
    assert second["session_status"] == "passed" and second["results"] == [True, True]
    row = await _kp_row(db_app, s, "distance-and-displacement", "kp1")
    assert row is not None and row.status == KpStatus.passed and row.passed_at is not None
    code, body = await _status(db_app, s, q_url(DIST, "kp1"))
    assert code == 409 and body["code"] == "kp_passed"

    lesson = await get(db_app, s, url(DIST))
    assert [k["status"] for k in lesson["kps"]] == ["passed", "not_started", "not_started"]
    async with db_app.sessions() as session:
        attempts = (await session.scalars(select(Attempt).order_by(Attempt.position))).all()
    kp_attempts = [a for a in attempts if a.session_id is not None]
    assert [a.position for a in kp_attempts] == [1, 2]
    assert all(
        (a.context == "kp" and "raw" in a.response) or "option" in a.response for a in kp_attempts
    )


async def test_wrong_answer_shows_the_answer_and_bad_inputs(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    q = await get(db_app, s, q_url(DIST, "kp1"))
    r = await db_app.client.post(
        a_url(DIST, "kp1"),
        json={"position": 1, "response": "1" * 201, "time_taken_ms": 1},
        headers=db_app.auth(s),
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_response"
    r = await db_app.client.post(
        a_url(DIST, "kp1"),
        json={"position": 3, "response": "1", "time_taken_ms": 1},
        headers=db_app.auth(s),
    )
    assert r.status_code == 409 and r.json()["code"] == "stale_question"
    wrong = await response_for(db_app, q, correct=False)
    res = await post(
        db_app, s, a_url(DIST, "kp1"), {"position": 1, "response": wrong, "time_taken_ms": 10**9}
    )
    assert res["correct"] is False and res["display_answer"]
    async with db_app.sessions() as session:
        att = await session.scalar(select(Attempt).where(Attempt.position == 1))
    assert att is not None and 0 <= att.time_taken_ms <= 1_800_000
    assert att.time_taken_ms < 60_000  # measured from when the question was served


async def test_two_answers_at_once_store_one_attempt(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    q = await get(db_app, s, q_url(DIST, "kp1"))
    body = {"position": 1, "response": await response_for(db_app, q), "time_taken_ms": 100}
    r1, r2 = await asyncio.gather(
        db_app.client.post(a_url(DIST, "kp1"), json=body, headers=db_app.auth(s)),
        db_app.client.post(a_url(DIST, "kp1"), json=body, headers=db_app.auth(s)),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert sorted([r1.json()["already_answered"], r2.json()["already_answered"]]) == [False, True]
    async with db_app.sessions() as session:
        positions = (await session.scalars(select(Attempt.position))).all()
    assert positions.count(1) == 1


async def test_two_tabs_opening_a_kp_share_one_session(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    r1, r2 = await asyncio.gather(
        db_app.client.get(q_url(DIST, "kp1"), headers=db_app.auth(s)),
        db_app.client.get(q_url(DIST, "kp1"), headers=db_app.auth(s)),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["session_id"] == r2.json()["session_id"]
    assert await count(db_app, PracticeSession) == 1


async def test_fail_waits_then_reopens_after_other_work(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    await answer_kp(db_app, s, DIST, "kp1", "CC")
    failed = await answer_kp(db_app, s, DIST, "kp2", "WWW")
    assert [r["session_status"] for r in failed] == ["active", "active", "failed"]
    assert failed[-1]["remediations"] == []  # first fail: no remediation
    row = await _kp_row(db_app, s, "distance-and-displacement", "kp2")
    assert row is not None and row.status == KpStatus.failed and row.fail_count == 1
    assert row.failed_at is not None and row.reopen_at == next_midnight_ist(row.failed_at)

    code, body = await _status(db_app, s, q_url(DIST, "kp2"))
    assert code == 409 and body["code"] == "kp_waiting"
    assert body["reopen_at"] and body["remediations"] == []
    lesson = await get(db_app, s, url(DIST))
    assert lesson["waiting"]["kp"] == "kp2"
    assert lesson["kps"][0]["status"] == "passed" and lesson["kps"][1]["open"] is False
    home = (await get(db_app, s, "/api/v1/learn/courses"))[0]
    assert [c["id"] for c in home["waiting"]] == [DIST]
    outline = await get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    dist = next(c for ch in outline["chapters"] for c in ch["concepts"] if c["id"] == DIST)
    assert dist["waiting"]["reopen_at"] and dist["kps_passed"] == 1 and dist["kps_total"] == 3

    async with db_app.sessions() as session:
        failed_items = {(a.item_id, a.seed) for a in (await session.scalars(select(Attempt))).all()}
    # Passing a KP in a different concept reopens it.
    await _open_lesson(db_app, s, LIN)
    await answer_kp(db_app, s, LIN, "kp1", "CC")
    lesson = await get(db_app, s, url(DIST))
    assert lesson["waiting"] is None and lesson["kps"][1]["open"] is True
    q = await get(db_app, s, q_url(DIST, "kp2"))
    async with db_app.sessions() as session:
        ps = await session.get(PracticeSession, uuid.UUID(q["session_id"]))
        assert ps is not None
    assert (ps.current_item_id, ps.current_seed) not in failed_items
    assert q["position"] == 1 and q["results"] == []


async def test_second_fail_review_fail_relearn(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    async with db_app.sessions() as session:  # also a Maths student: LIN shows in both courses
        session.add(Enrollment(org_id=w.a.org_id, class_id=w.a.class_ids[0], student_id=s))
        await session.commit()
    await learn_concept(db_app, s, DIST)
    await learn_concept(db_app, s, LIN)
    await _open_lesson(db_app, s, SPEED)
    await answer_kp(db_app, s, SPEED, "kp1", "CC")
    await answer_kp(db_app, s, SPEED, "kp2", "CC")
    await answer_kp(db_app, s, SPEED, "kp3", "WWW")
    await _cooldown_over(db_app, s)
    second = await answer_kp(db_app, s, SPEED, "kp3", "WWW")
    rems = second[-1]["remediations"]
    assert [(r["kind"], r["prereq"]["id"], r["concept"]["id"]) for r in rems] == [
        ("review", LIN, SPEED)
    ]
    rid = rems[0]["id"]
    await _cooldown_over(db_app, s)
    code, body = await _status(db_app, s, q_url(SPEED, "kp3"))
    assert code == 409 and body["code"] == "kp_waiting"  # blocked by the open remediation
    assert [r["id"] for r in body["remediations"]] == [rid]
    home = {c["slug"]: c for c in await get(db_app, s, "/api/v1/learn/courses")}
    assert [b["id"] for b in home[PHYSICS]["brush_up"]] == [rid]
    info = await get(db_app, s, f"/api/v1/learn/remediations/{rid}")
    assert info["kind"] == "review" and info["prereq"]["id"] == LIN

    # Fail the review: LIN is relearned (in progress in both courses); SPEED never re-locks.
    for _ in range(3):
        q = await get(db_app, s, f"/api/v1/learn/remediations/{rid}/question")
        response = await response_for(db_app, q, correct=False)
        res = await post(
            db_app,
            s,
            f"/api/v1/learn/remediations/{rid}/answer",
            {"position": q["position"], "response": response, "time_taken_ms": 100},
        )
    assert res["session_status"] == "failed"
    for course in (MATHS, PHYSICS):
        outline = await get(db_app, s, f"/api/v1/learn/courses/{course}/outline")
        assert statuses(outline)[LIN] == "in_progress"
    outline = await get(db_app, s, f"/api/v1/learn/courses/{PHYSICS}/outline")
    assert statuses(outline)[SPEED] == "in_progress"
    async with db_app.sessions() as session:
        rem = await session.get(Remediation, uuid.UUID(rid))
        lin = await session.scalar(
            select(ConceptState).where(
                ConceptState.student_id == s, ConceptState.concept_id.in_(_concept_ids(LIN_SLUG))
            )
        )
    assert rem is not None and rem.state == RemediationState.relearn
    assert lin is not None and lin.relearn_count == 1 and lin.learned_at is None
    code, body = await _status(db_app, s, f"/api/v1/learn/remediations/{rid}/question")
    assert code == 409 and body["code"] == "not_due"

    # Relearn LIN: the remediation resolves and SPEED's kp3 opens (a KP passed elsewhere).
    lesson = await get(db_app, s, url(LIN))
    assert [k["status"] for k in lesson["kps"]] == ["not_started"] * 3
    await learn_concept(db_app, s, LIN)
    async with db_app.sessions() as session:
        rem = await session.get(Remediation, uuid.UUID(rid))
    assert rem is not None and rem.state == RemediationState.resolved
    assert rem.outcome == "relearned"
    q = await get(db_app, s, q_url(SPEED, "kp3"))
    assert q["position"] == 1


async def test_review_pass_resolves_and_reopens(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await learn_concept(db_app, s, DIST)
    await learn_concept(db_app, s, LIN)
    await _open_lesson(db_app, s, SPEED)
    await answer_kp(db_app, s, SPEED, "kp1", "WWW")
    await _cooldown_over(db_app, s)
    second = await answer_kp(db_app, s, SPEED, "kp1", "WWW")
    rid = second[-1]["remediations"][0]["id"]
    assert second[-1]["remediations"][0]["prereq"]["id"] == DIST
    for _ in range(3):
        q = await get(db_app, s, f"/api/v1/learn/remediations/{rid}/question")
        res = await post(
            db_app,
            s,
            f"/api/v1/learn/remediations/{rid}/answer",
            {
                "position": q["position"],
                "response": await response_for(db_app, q),
                "time_taken_ms": 100,
            },
        )
    assert res["session_status"] == "passed"
    async with db_app.sessions() as session:
        rem = await session.get(Remediation, uuid.UUID(rid))
        learned = await session.scalar(
            select(ConceptState.status).where(
                ConceptState.student_id == s,
                ConceptState.concept_id.in_(_concept_ids("distance-and-displacement")),
            )
        )
    assert rem is not None and rem.state == RemediationState.resolved
    assert rem.outcome == "review_passed"
    assert learned == ConceptStatus.learned  # a review never changes the prereq's state
    # The review pass counts as "other work": kp1 is open now (the cooldown hasn't run out).
    async with db_app.sessions() as session:
        await session.execute(
            update(KpProgress)
            .where(KpProgress.student_id == s, KpProgress.status == KpStatus.failed)
            .values(reopen_at=datetime.now(UTC) + timedelta(hours=5))
        )
        await session.commit()
    q = await get(db_app, s, q_url(SPEED, "kp1"))
    assert q["position"] == 1


async def test_learning_every_kp_learns_the_concept_and_unlocks(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await learn_concept(db_app, s, DIST)
    last = await learn_concept(db_app, s, LIN)
    assert last["concept_learned"] is True
    assert [c["id"] for c in last["unlocked"]] == [SPEED]
    last = await learn_concept(db_app, s, SPEED)
    assert [c["id"] for c in last["unlocked"]] == [ACCEL]
    async with db_app.sessions() as session:
        rows = (await session.scalars(select(ConceptState))).all()
    assert {r.status for r in rows} == {ConceptStatus.learned} and len(rows) == 3
    home = (await get(db_app, s, "/api/v1/learn/courses"))[0]
    assert home["learned"] == 3 and [c["id"] for c in home["ready"]] == [ACCEL]
    lesson = await get(db_app, s, url(SPEED))
    assert lesson["concept_status"] == "learned"
    assert {k["status"] for k in lesson["kps"]} == {"passed"}
    async with db_app.sessions() as session:
        activities = set((await session.scalars(select(StudyTime.activity))).all())
    assert activities == {"learn"}  # practice time is posted by the client on kpq steps


async def test_practice_time_on_kpq_and_remediation_steps(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await post(db_app, s, url(DIST, "/progress"), {"step": "kpq:kp1", "active_seconds": 20})
    await post(db_app, s, url(DIST, "/progress"), {"step": "remediation", "active_seconds": 7})
    async with db_app.sessions() as session:
        rows = (await session.scalars(select(StudyTime).order_by(StudyTime.id))).all()
        progress = await session.scalar(select(LessonProgress))
    assert [(r.activity, r.step, r.active_seconds) for r in rows] == [
        ("practice", "kpq:kp1", 20),
        ("practice", "remediation", 7),
    ]
    assert progress is not None and progress.seen_steps == ["kpq:kp1"]


async def test_staff_preview_answers_and_writes_nothing(db_app: DbApp) -> None:
    w = await world(db_app)
    t = w.a.teacher_id
    q = await get(db_app, t, q_url(SPEED, "kp3"))  # no check / order / lock rules for staff
    assert q["session_id"] is None and q["results"] == []
    assert not (keys(q) & LEAKS)
    body = {
        "position": 1,
        "response": await response_for(db_app, q),
        "time_taken_ms": 10,
        "item_id": q["item_id"],
        "seed": q["preview_seed"],
    }
    res = await post(db_app, t, a_url(SPEED, "kp3"), body)
    assert res["correct"] is True and res["session_status"] == "active"
    r = await db_app.client.post(
        a_url(SPEED, "kp3"),
        json={"position": 1, "response": "1", "time_taken_ms": 1},
        headers=db_app.auth(t),
    )
    assert r.status_code == 422
    for model in (
        Attempt,
        PracticeSession,
        KpProgress,
        ConceptState,
        Remediation,
        StudyTime,
        LessonProgress,
    ):
        assert await count(db_app, model) == 0, model
    r = await db_app.client.get(
        f"/api/v1/learn/remediations/{uuid.uuid4()}/question", headers=db_app.auth(t)
    )
    assert r.status_code == 403


async def test_other_school_gets_404(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await learn_concept(db_app, s, DIST)
    await _open_lesson(db_app, s, LIN)
    await answer_kp(db_app, s, LIN, "kp1", "WWW")
    await _cooldown_over(db_app, s)
    # LIN has no key prereqs on kp1; craft a remediation directly to test isolation.
    async with db_app.sessions() as session:
        kp_id = await session.scalar(
            select(KnowledgePoint.id).where(KnowledgePoint.concept_id.in_(_concept_ids(LIN_SLUG)))
        )
        dist_id = await session.scalar(_concept_ids("distance-and-displacement"))
        rem = Remediation(
            id=uuid.uuid4(),
            org_id=w.a.org_id,
            student_id=s,
            kp_id=kp_id,
            prereq_concept_id=dist_id,
            state=RemediationState.review_due,
        )
        session.add(rem)
        await session.commit()
    for other in (w.b.student_ids[3], w.a.student_ids[4]):  # school B; same school, other student
        for path in (
            f"/api/v1/learn/remediations/{rem.id}",
            f"/api/v1/learn/remediations/{rem.id}/question",
            "/api/v1/learn/remediations/not-a-uuid",
        ):
            r = await db_app.client.get(path, headers=db_app.auth(other))
            assert r.status_code == 404, (path, r.text)
