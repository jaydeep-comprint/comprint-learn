"""The mixed timed quiz (spec 007) on a real database: creation at 150 XP, blocking, saving
without feedback, the timer, the result, misses as reviews, XP per subject, scoping."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.models import (
    Quiz,
    QuizStatus,
    ReviewDueReason,
    Subject,
    XpDay,
    XpEvent,
    XpGrade,
    XpReason,
)
from app.services import quiz as quiz_service
from tests.conftest import DbApp
from tests.learn_helpers import (
    ACCEL,
    DIST,
    LIN,
    SPEED,
    answer_check,
    answer_fields,
    get,
    keys,
    post,
    url,
    world,
)
from tests.review_helpers import (
    card,
    concept_id,
    do_review,
    make_due,
    offered_refs,
    queue,
    review_path,
    seed_learned,
)

pytestmark = pytest.mark.db

QUIZZES = "/api/v1/quizzes"
ANSWER_KEYS = {"display_answer", "explanation_md", "correct", "answer"}


async def _status(db: DbApp, user: uuid.UUID, path: str) -> tuple[int, dict[str, Any]]:
    r = await db.client.get(path, headers=db.auth(user))
    return r.status_code, r.json()


async def _post_status(
    db: DbApp, user: uuid.UUID, path: str, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    r = await db.client.post(path, json=body or {}, headers=db.auth(user))
    return r.status_code, r.json()


async def _seed_xp(db: DbApp, org_id: uuid.UUID, user: uuid.UUID, amount: int) -> None:
    """Lifetime XP without sessions (a manual seed, as the spec's verification allows)."""
    async with db.sessions() as session:
        session.add(
            XpEvent(
                org_id=org_id,
                student_id=user,
                session_id=None,
                reason=XpReason.kp,
                concept_id=await concept_id(db, DIST),
                subject=Subject.physics,
                amount=amount,
                grade=XpGrade.passed,
                base_minutes=amount,
                answered=1,
                rushed_count=0,
                hints=0,
                day=date.today(),
            )
        )
        await session.commit()


async def _quizzes(db: DbApp, user: uuid.UUID) -> list[Quiz]:
    async with db.sessions() as session:
        rows = await session.scalars(
            select(Quiz).where(Quiz.student_id == user).order_by(Quiz.created_at)
        )
        return list(rows.all())


async def _ready(db: DbApp) -> tuple[Any, uuid.UUID]:
    """A physics student with 3 learned concepts (maths and physics) and 149 XP, with DIST due."""
    w = await world(db)
    s = w.physics_student
    await seed_learned(db, w.a.org_id, s, [DIST, SPEED, LIN])
    await _seed_xp(db, w.a.org_id, s, 149)
    await make_due(db, s, DIST)
    return w, s


async def _create_quiz(db: DbApp, s: uuid.UUID) -> dict[str, Any]:
    """The review's XP award crosses 150: a pending quiz."""
    await do_review(db, s, DIST, "CCC")
    current: dict[str, Any] = await get(db, s, f"{QUIZZES}/current")
    assert current is not None and current["status"] == "pending"
    return current


async def _answer_all(db: DbApp, s: uuid.UUID, qid: str, pattern: str) -> list[dict[str, Any]]:
    out = []
    for c in pattern:
        q = await get(db, s, f"{QUIZZES}/{qid}/question")
        assert q["results"] == [] and q["deadline"] is not None
        body = {"position": q["position"], "time_taken_ms": 60_000}
        body |= await answer_fields(db, q, correct=c == "C")
        saved = await post(db, s, f"{QUIZZES}/{qid}/answer", body)
        assert set(saved) == {"saved", "answered", "finished"}
        out.append(saved)
    return out


async def test_award_crossing_150_creates_one_quiz_and_blocks_new_kps(db_app: DbApp) -> None:
    _w, s = await _ready(db_app)
    assert await get(db_app, s, f"{QUIZZES}/current") is None
    # Open ACCEL's first KP before the quiz exists: that session may be finished later.
    await post(db_app, s, url(ACCEL, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, ACCEL)
    open_q = await get(db_app, s, url(ACCEL, "/kps/kp1/question"))
    current = await _create_quiz(db_app, s)
    assert current["total"] == 10 and current["minutes"] == 15
    assert len(await _quizzes(db_app, s)) == 1
    # Another award doesn't create a second one.
    await make_due(db_app, s, SPEED)
    await do_review(db_app, s, SPEED, "CCC")  # reviews aren't blocked by a pending quiz
    assert len(await _quizzes(db_app, s)) == 1
    # The open KP session continues (two right answers pass kp1)...
    q = open_q
    for _ in range(2):
        body = {"position": q["position"], "time_taken_ms": 60_000}
        body |= await answer_fields(db_app, q)
        res = await post(db_app, s, url(ACCEL, "/kps/kp1/answer"), body)
        if res["session_status"] == "active":
            q = await get(db_app, s, url(ACCEL, "/kps/kp1/question"))
            assert q["session_id"] == open_q["session_id"]
    assert res["session_status"] == "passed"
    # ...but a new KP session isn't opened.
    code, err = await _status(db_app, s, url(ACCEL, "/kps/kp2/question"))
    assert code == 409 and err["code"] == "quiz_pending"
    assert err["quiz_id"] == current["id"]


async def test_no_quiz_with_fewer_than_three_learned_concepts(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST, LIN])
    await _seed_xp(db_app, w.a.org_id, s, 400)
    await make_due(db_app, s, DIST)
    await do_review(db_app, s, DIST, "CCC")
    assert await _quizzes(db_app, s) == []


async def test_quiz_saves_without_feedback_then_reveals_the_result(db_app: DbApp) -> None:
    _w, s = await _ready(db_app)
    qid = (await _create_quiz(db_app, s))["id"]
    code, err = await _status(db_app, s, f"{QUIZZES}/{qid}/question")
    assert code == 409 and err["code"] == "quiz_not_started"
    started = await post(db_app, s, f"{QUIZZES}/{qid}/start", {})
    assert started["status"] == "active" and started["total"] == 10
    assert 880 <= started["seconds_left"] <= 900
    again = await post(db_app, s, f"{QUIZZES}/{qid}/start", {})
    assert again["deadline"] == started["deadline"]  # idempotent
    code, err = await _status(db_app, s, f"{QUIZZES}/{qid}/result")
    assert code == 409 and err["code"] == "quiz_not_finished"
    q = await get(db_app, s, f"{QUIZZES}/{qid}/question")
    assert not keys(q) & ANSWER_KEYS
    saved = await _answer_all(db_app, s, qid, "CCCCCCCWWW")
    assert [x["finished"] for x in saved] == [False] * 9 + [True]
    assert not any(keys(x) & ANSWER_KEYS for x in saved)
    # A resend of a saved answer gets "saved" again, never correctness.
    status, resent = await _post_status(
        db_app, s, f"{QUIZZES}/{qid}/answer", {"position": 1, "response": "1", "time_taken_ms": 1}
    )
    assert status == 200 and resent["saved"] is True and "correct" not in resent
    result = await get(db_app, s, f"{QUIZZES}/{qid}/result")
    assert (result["correct"], result["total"]) == (7, 10)
    assert [i["correct"] for i in result["items"]] == [True] * 7 + [False] * 3
    assert all(i["display_answer"] and i["response"] is not None for i in result["items"])
    missed = {i["concept"]["id"] for i in result["items"] if not i["correct"]}
    assert {c["id"] for c in result["review_concepts"]} == missed
    for ref in missed:
        c = await card(db_app, s, ref)
        assert c is not None and c.due_reason == ReviewDueReason.quiz_miss
    q = await queue(db_app, s)
    assert set(missed) <= set(offered_refs(q))
    assert all(o["reason"] == "quiz_miss" for o in q["offered"] if o["concept"]["id"] in missed)
    # XP: one event per subject in the quiz, each on that subject's day.
    async with db_app.sessions() as session:
        events = (
            await session.scalars(
                select(XpEvent).where(XpEvent.student_id == s, XpEvent.reason == XpReason.quiz)
            )
        ).all()
        days = {
            d.subject: d
            for d in (await session.scalars(select(XpDay).where(XpDay.student_id == s))).all()
        }
    subjects = {e.subject for e in events}
    assert len(events) == len(subjects) and subjects <= {Subject.maths, Subject.physics}
    assert {x["subject"] for x in result["xp"]["subjects"]} == {s_.value for s_ in subjects}
    assert result["xp"]["amount"] == sum(e.amount for e in events)
    for e in events:
        assert e.subject in days
    # Finished: the quiz no longer blocks, and the next mark is 150 above lifetime XP.
    assert await get(db_app, s, f"{QUIZZES}/current") is None
    [finished] = await _quizzes(db_app, s)
    assert finished.status == QuizStatus.finished and finished.next_mark is not None
    async with db_app.sessions() as session:
        lifetime = sum(
            (await session.scalars(select(XpEvent.amount).where(XpEvent.student_id == s))).all()
        )
    assert finished.next_mark == lifetime + quiz_service.QUIZ_MARK


async def test_late_answer_and_lazy_finish(db_app: DbApp) -> None:
    _w, s = await _ready(db_app)
    qid = (await _create_quiz(db_app, s))["id"]
    await post(db_app, s, f"{QUIZZES}/{qid}/start", {})
    await _answer_all(db_app, s, qid, "CC")
    q = await get(db_app, s, f"{QUIZZES}/{qid}/question")
    async with db_app.sessions() as session:
        await session.execute(
            update(Quiz)
            .where(Quiz.id == uuid.UUID(qid))
            .values(deadline=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    body = {"position": q["position"], "time_taken_ms": 1000}
    body |= await answer_fields(db_app, q)
    code, err = await _post_status(db_app, s, f"{QUIZZES}/{qid}/answer", body)
    assert code == 409 and err["code"] == "quiz_over"
    result = await get(db_app, s, f"{QUIZZES}/{qid}/result")
    assert result["correct"] == 2 and result["total"] == 10
    assert [i["response"] is None for i in result["items"]] == [False] * 2 + [True] * 8


async def test_reading_after_the_deadline_finishes_the_quiz(db_app: DbApp) -> None:
    _w, s = await _ready(db_app)
    qid = (await _create_quiz(db_app, s))["id"]
    await post(db_app, s, f"{QUIZZES}/{qid}/start", {})
    async with db_app.sessions() as session:
        await session.execute(
            update(Quiz)
            .where(Quiz.id == uuid.UUID(qid))
            .values(deadline=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert await get(db_app, s, f"{QUIZZES}/current") is None
    [q] = await _quizzes(db_app, s)
    assert q.status == QuizStatus.finished and q.correct == 0
    async with db_app.sessions() as session:
        quiz_events = (
            await session.scalars(
                select(XpEvent).where(XpEvent.student_id == s, XpEvent.reason == XpReason.quiz)
            )
        ).all()
    assert quiz_events and all(e.amount == 0 for e in quiz_events)  # time-out still awards
    code, err = await _status(db_app, s, f"{QUIZZES}/{qid}/question")
    assert code == 409 and err["code"] == "quiz_over"


async def test_quiz_is_the_students_own(db_app: DbApp) -> None:
    w, s = await _ready(db_app)
    qid = (await _create_quiz(db_app, s))["id"]
    for other in (w.a.student_ids[0], w.b.student_ids[3]):
        code, _ = await _status(db_app, other, f"{QUIZZES}/{qid}")
        assert code == 404
        code, _ = await _post_status(db_app, other, f"{QUIZZES}/{qid}/start")
        assert code == 404
    for staff in (w.a.teacher_id, w.b.teacher_id):
        code, _ = await _status(db_app, staff, f"{QUIZZES}/current")
        assert code == 403
        code, _ = await _status(db_app, staff, f"{QUIZZES}/{qid}/result")
        assert code == 403
    code, _ = await _status(db_app, s, f"{QUIZZES}/not-a-uuid")
    assert code == 404


async def test_roster_last_quiz(db_app: DbApp) -> None:
    w, s = await _ready(db_app)
    qid = (await _create_quiz(db_app, s))["id"]
    await post(db_app, s, f"{QUIZZES}/{qid}/start", {})
    await _answer_all(db_app, s, qid, "CCCCCCCCWW")
    rows = await get(db_app, w.a.teacher_id, f"/api/v1/classes/{w.a.class_ids[1]}/students")
    me = next(r for r in rows if r["id"] == str(s))
    assert me["last_quiz"]["score_pct"] == 80
    assert me["reviews_due"] >= 1  # the misses


async def test_review_page_route_needs_the_concept_in_the_course(db_app: DbApp) -> None:
    _w, s = await _ready(db_app)
    code, _ = await _status(
        db_app, s, f"{review_path('maths-9-10/distance-and-displacement')}/question"
    )
    assert code == 404
