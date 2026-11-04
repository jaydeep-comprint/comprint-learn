"""The Practice step, multi-step problems and code questions (spec 006) on a real database."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, update

from app.grading import QUICK_TYPES
from app.models import (
    Attempt,
    AttemptContext,
    Concept,
    Enrollment,
    Item,
    KnowledgePoint,
    PracticeSession,
    SchoolClass,
    SessionKind,
    StudyTime,
    Subject,
)
from app.models.content import ItemKind, ItemType
from app.services import kp_flow
from tests.conftest import DbApp
from tests.db_seed import student
from tests.learn_helpers import (
    DIST,
    LIN,
    MATHS,
    answer_check,
    answer_fields,
    answer_kp,
    code_spec,
    count,
    get,
    keys,
    learn_concept,
    post,
    url,
    world,
)

pytestmark = pytest.mark.db

GRAPHICAL = f"{MATHS}/pair-of-linear-equations-graphical"
ALGEBRAIC = f"{MATHS}/pair-of-linear-equations-algebraic"
PY_VARS = "python-basics/variables-and-types"
LEAKS = {"answer", "params", "solution", "spec", "explanation_md", "display_answer"}


def p_url(ref: str, tail: str) -> str:
    return url(ref, f"/practice/{tail}")


async def _status(db: DbApp, user: uuid.UUID, path: str) -> tuple[int, Any]:
    r = await db.client.get(path, headers=db.auth(user))
    return r.status_code, r.json()


async def _post_status(
    db: DbApp, user: uuid.UUID, path: str, body: dict[str, Any]
) -> tuple[int, Any]:
    r = await db.client.post(path, json=body, headers=db.auth(user))
    return r.status_code, r.json()


async def _pass_kps(db: DbApp, user: uuid.UUID, ref: str) -> Any:
    lesson = await get(db, user, url(ref))
    await post(db, user, url(ref, "/progress"), {"step": "intro", "active_seconds": 5})
    if lesson["check"] is not None and lesson["check_result"] is None:
        await answer_check(db, user, ref)
    for kp in lesson["kps"]:
        await answer_kp(db, user, ref, kp["slug"])
    return lesson


async def _answer_step(
    db: DbApp, user: uuid.UUID, ref: str, q: dict[str, Any], *, correct: bool
) -> dict[str, Any]:
    body = {"position": q["position"], "time_taken_ms": 2000}
    body |= await answer_fields(db, q, correct=correct)
    return await post(db, user, p_url(ref, "answer"), body)  # type: ignore[no-any-return]


async def _python_student(db: DbApp, org_id: uuid.UUID, teacher_id: uuid.UUID) -> uuid.UUID:
    """A student in a Python class (the seed has maths and physics classes only)."""
    async with db.sessions() as session:
        cls = SchoolClass(
            id=uuid.uuid4(),
            org_id=org_id,
            name="9C python",
            subject=Subject.python,
            grade=9,
            created_by=teacher_id,
        )
        s = student(org_id, f"py{uuid.uuid4().hex[:6]}")
        session.add_all([cls, s])
        await session.flush()
        session.add(Enrollment(org_id=org_id, class_id=cls.id, student_id=s.id))
        await session.commit()
        return s.id


def _concept_status(outline: dict[str, Any], ref: str) -> dict[str, Any]:
    return next(c for ch in outline["chapters"] for c in ch["concepts"] if c["id"] == ref)


async def test_practice_locked_until_kps_pass_then_pending(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    lesson = await get(db_app, s, url(DIST))
    assert lesson["steps"][-1] == "practice"
    assert lesson["practice"] == {"status": "pending", "active": False}
    await post(db_app, s, url(DIST, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, DIST)
    code, body = await _status(db_app, s, p_url(DIST, "question"))
    assert code == 409 and body["code"] == "practice_locked"

    last = (await answer_kp(db_app, s, DIST, "kp1"))[-1]
    await answer_kp(db_app, s, DIST, "kp2")
    last = (await answer_kp(db_app, s, DIST, "kp3"))[-1]
    assert last["session_status"] == "passed" and last["concept_learned"] is False

    outline = await get(db_app, s, f"/api/v1/learn/courses/{DIST.split('/')[0]}/outline")
    concept = _concept_status(outline, DIST)
    assert concept["status"] == "in_progress"
    assert (concept["parts_passed"], concept["parts_total"]) == (3, 4)
    home = await get(db_app, s, "/api/v1/learn/courses")
    [entry] = [c for course in home for c in course["in_progress"] if c["id"] == DIST]
    assert entry["practice_left"] is True and entry["parts_total"] == 4
    lesson = await get(db_app, s, url(DIST))
    assert lesson["concept_status"] == "in_progress"
    assert lesson["practice"]["status"] == "pending"

    # The practice step logs practice time.
    await post(db_app, s, url(DIST, "/progress"), {"step": "practice", "active_seconds": 30})
    async with db_app.sessions() as session:
        activity = await session.scalar(
            select(StudyTime.activity).where(
                StudyTime.student_id == s, StudyTime.step == "practice"
            )
        )
    assert activity is not None and activity.value == "practice"


async def test_multistep_practice_step_order_resume_and_pass(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.maths_student
    await learn_concept(db_app, s, LIN)
    await _pass_kps(db_app, s, GRAPHICAL)

    q = await get(db_app, s, p_url(GRAPHICAL, "question"))
    assert q["type"] == "multistep" and q["step"] == 0 and q["step_results"] == []
    assert len(q["steps"]) == 4 and "{{" not in q["prompt_md"]
    assert not (keys(q) & LEAKS), keys(q) & LEAKS
    lesson = await get(db_app, s, url(GRAPHICAL))
    assert lesson["practice"] == {"status": "pending", "active": True}

    fields = await answer_fields(db_app, q)
    code, body = await _post_status(
        db_app,
        s,
        p_url(GRAPHICAL, "answer"),
        {**fields, "position": 1, "step": 1, "time_taken_ms": 100},
    )
    assert code == 409 and body["code"] == "step_order"

    first = await _answer_step(db_app, s, GRAPHICAL, q, correct=True)
    assert first["correct"] and first["item_done"] is False and first["step"] == 0
    assert first["session_status"] == "active" and first["explanation_md"] is None
    assert first["results"] == []  # the item isn't done yet

    again = await get(db_app, s, p_url(GRAPHICAL, "question"))
    assert again["step"] == 1 and again["prompt_md"] == q["prompt_md"]
    assert [r["correct"] for r in again["step_results"]] == [True]

    wrong = await _answer_step(db_app, s, GRAPHICAL, again, correct=False)
    assert wrong["correct"] is False and wrong["step_results"][-1]["display_answer"]
    for _ in range(2):
        nxt = await get(db_app, s, p_url(GRAPHICAL, "question"))
        last = await _answer_step(db_app, s, GRAPHICAL, nxt, correct=True)
    assert last["item_done"] and last["item_correct"] is True  # 3 of 4, the last one right
    assert [r["correct"] for r in last["step_results"]] == [True, False, True, True]
    assert last["session_status"] == "passed" and last["concept_learned"] is True
    assert ALGEBRAIC in [u["id"] for u in last["unlocked"]]
    assert last["explanation_md"]

    code, body = await _status(db_app, s, p_url(GRAPHICAL, "question"))
    assert code == 409 and body["code"] == "practice_passed"
    lesson = await get(db_app, s, url(GRAPHICAL))
    assert lesson["concept_status"] == "learned" and lesson["practice"]["status"] == "passed"
    async with db_app.sessions() as session:
        rows = (
            await session.scalars(
                select(Attempt).where(Attempt.session_id == uuid.UUID(q["session_id"]))
            )
        ).all()
    assert sorted(a.step for a in rows) == [0, 1, 2, 3]
    assert {a.position for a in rows} == {1}


async def test_failed_multistep_try_again_draws_new_numbers(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _pass_kps(db_app, s, DIST)
    q = await get(db_app, s, p_url(DIST, "question"))
    while True:
        res = await _answer_step(db_app, s, DIST, q, correct=False)
        if res["item_done"]:
            break
        q = await get(db_app, s, p_url(DIST, "question"))
    assert res["session_status"] == "failed" and res["concept_learned"] is False
    assert res["item_correct"] is False and res["explanation_md"]

    retry = await get(db_app, s, p_url(DIST, "question"))
    assert retry["session_id"] != q["session_id"] and retry["step"] == 0
    async with db_app.sessions() as session:
        sessions = (
            await session.scalars(
                select(PracticeSession)
                .where(PracticeSession.kind == SessionKind.practice)
                .order_by(PracticeSession.started_at)
            )
        ).all()
    assert [p.status.value for p in sessions] == ["failed", "active"]
    assert sessions[0].current_item_id == sessions[1].current_item_id  # only one practice item
    assert sessions[0].current_seed != sessions[1].current_seed  # new numbers


async def test_code_practice_retry_prefill_then_pass(db_app: DbApp) -> None:
    w = await world(db_app)
    s = await _python_student(db_app, w.a.org_id, w.a.teacher_id)
    await _pass_kps(db_app, s, PY_VARS)
    q = await get(db_app, s, p_url(PY_VARS, "question"))
    assert q["type"] == "code" and q["code"]["prefill"] is None
    hidden = [t for t in q["code"]["tests"] if not t["visible"]]
    assert hidden and all(t["expected"] is None and t["expected_stdout"] is None for t in hidden)
    assert not (keys(q) & LEAKS)

    starter = await answer_fields(db_app, q, correct=False)
    failed = await post(
        db_app, s, p_url(PY_VARS, "answer"), {"position": 1, "time_taken_ms": 9000, **starter}
    )
    assert failed["correct"] is False and failed["session_status"] == "failed"
    assert failed["solution"] is None and failed["explanation_md"] is None
    assert all(t["expected"] is None for t in failed["tests"] if not t["visible"])
    assert any(t["expected"] is not None for t in failed["tests"] if t["visible"])

    retry = await get(db_app, s, p_url(PY_VARS, "question"))
    assert retry["item_id"] == q["item_id"] and retry["session_id"] != q["session_id"]
    assert retry["code"]["prefill"] == starter["code"]

    passed = await post(
        db_app,
        s,
        p_url(PY_VARS, "answer"),
        {"position": 1, "time_taken_ms": 9000, **await answer_fields(db_app, retry)},
    )
    assert passed["correct"] and passed["session_status"] == "passed"
    assert passed["concept_learned"] is True and passed["solution"]
    async with db_app.sessions() as session:
        stored = await session.scalar(
            select(Attempt.response).where(
                Attempt.context == AttemptContext.practice, Attempt.correct.is_(True)
            )
        )
    assert stored is not None and set(stored) == {"code", "outputs", "verdicts"}
    assert all(set(o) <= {"value", "stdout", "error", "timeout"} for o in stored["outputs"])


async def test_code_kp_question_counts_and_double_submit_stores_one(db_app: DbApp) -> None:
    w = await world(db_app)
    s = await _python_student(db_app, w.a.org_id, w.a.teacher_id)
    lesson = await get(db_app, s, url(PY_VARS))
    await post(db_app, s, url(PY_VARS, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, PY_VARS)
    kp = lesson["kps"][0]["slug"]
    path = url(PY_VARS, f"/kps/{kp}")
    q = await get(db_app, s, f"{path}/question")
    async with db_app.sessions() as session:
        code_item = await session.scalar(
            select(Item).where(
                Item.kp_id.in_(select(KnowledgePoint.id).where(KnowledgePoint.slug == kp)),
                Item.concept_id.in_(
                    select(Concept.id).where(Concept.slug == PY_VARS.split("/")[1])
                ),
                Item.type == ItemType.code,
            )
        )
        assert code_item is not None
        await session.execute(
            update(PracticeSession)
            .where(PracticeSession.id == uuid.UUID(q["session_id"]))
            .values(current_item_id=code_item.id, current_seed=None)
        )
        await session.commit()
    q = await get(db_app, s, f"{path}/question")
    assert q["type"] == "code" and not (keys(q) & LEAKS)

    body = {"position": 1, "time_taken_ms": 5000, **await answer_fields(db_app, q)}
    for bad in (
        dict(body, outputs=body["outputs"][:-1]),  # one output short
        dict(body, code="x" * 20_001),  # code too long
        dict(body, outputs=[{"stdout": "x" * 20_000}] * len(body["outputs"])),
    ):
        code, problem = await _post_status(db_app, s, f"{path}/answer", bad)
        assert code == 422 and problem["code"] == "invalid_response"
    assert await count(db_app, Attempt, item_id=code_item.id) == 0

    r1, r2 = await asyncio.gather(
        db_app.client.post(f"{path}/answer", json=body, headers=db_app.auth(s)),
        db_app.client.post(f"{path}/answer", json=body, headers=db_app.auth(s)),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    results = [r1.json(), r2.json()]
    assert sorted(r["already_answered"] for r in results) == [False, True]
    assert all(r["correct"] and r["solution"] for r in results)  # KP: the solution is shown
    assert await count(db_app, Attempt, item_id=code_item.id) == 1


async def test_unit_rules_on_kp_answers(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await post(db_app, s, url(DIST, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, DIST)
    path = url(DIST, "/kps/kp1")
    q = await get(db_app, s, f"{path}/question")
    fields = await answer_fields(db_app, q)
    if q["unit_required"]:
        code, problem = await _post_status(
            db_app,
            s,
            f"{path}/answer",
            {**fields, "unit": "x" * 41, "position": 1, "time_taken_ms": 1},
        )
        assert code == 422 and problem["code"] == "invalid_response"
        no_unit = {k: v for k, v in fields.items() if k != "unit"}
        res = await post(
            db_app, s, f"{path}/answer", {**no_unit, "position": 1, "time_taken_ms": 1}
        )
        assert res["correct"] is False and res["note"].startswith("Add a unit")
    else:
        code, problem = await _post_status(
            db_app, s, f"{path}/answer", {**fields, "unit": "m", "position": 1, "time_taken_ms": 1}
        )
        assert code == 422 and problem["code"] == "invalid_unit_field"


async def test_reviews_never_serve_code_or_multistep(db_app: DbApp) -> None:
    await world(db_app)
    async with db_app.sessions() as session:
        kp_ids = (
            await session.scalars(
                select(Item.kp_id).where(Item.type == ItemType.code, Item.kp_id.is_not(None))
            )
        ).all()
        assert kp_ids
        scope: Any = SimpleNamespace(session=session)
        for kp_id in kp_ids:
            assert kp_id is not None
            review = await kp_flow._pool(scope, kp_id, QUICK_TYPES)
            assert review and all(i.type.value in QUICK_TYPES for i in review)
            full = await kp_flow._pool(scope, kp_id)
            assert any(i.type == ItemType.code for i in full)


async def test_staff_preview_writes_nothing(db_app: DbApp) -> None:
    w = await world(db_app)
    t = w.a.teacher_id
    for ref in (DIST, PY_VARS):
        q = await get(db_app, t, p_url(ref, "question"))  # no KP gate for staff
        assert q["session_id"] is None
        body: dict[str, Any] = {"position": 1, "time_taken_ms": 1, "item_id": q["item_id"]}
        body["seed"] = q["preview_seed"]
        body |= await answer_fields(db_app, q)
        res = await post(db_app, t, p_url(ref, "answer"), body)
        assert res["correct"] is True
        if q["type"] == "code":
            assert res["solution"] and res["tests"]
        else:
            assert res["step"] == 0 and res["item_done"] is False
    assert await count(db_app, Attempt) == 0
    assert await count(db_app, PracticeSession) == 0


async def test_practise_again_on_a_learned_concept_writes_nothing(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await learn_concept(db_app, s, DIST)
    code, body = await _status(db_app, s, p_url(DIST, "question"))
    assert code == 409 and body["code"] == "practice_passed"
    before = await count(db_app, Attempt)
    q = await get(db_app, s, p_url(DIST, "question?again=true"))
    assert q["session_id"] is None and q["preview_seed"] is not None
    res = await post(
        db_app,
        s,
        p_url(DIST, "answer?again=true"),
        {
            "position": 1,
            "time_taken_ms": 1,
            "item_id": q["item_id"],
            "seed": q["preview_seed"],
            **await answer_fields(db_app, q),
        },
    )
    assert res["correct"] is True
    assert await count(db_app, Attempt) == before


async def test_other_school_and_other_courses_get_404(db_app: DbApp) -> None:
    w = await world(db_app)
    s = await _python_student(db_app, w.a.org_id, w.a.teacher_id)
    await _pass_kps(db_app, s, PY_VARS)
    mine = await get(db_app, s, p_url(PY_VARS, "question"))
    for other in (w.b.student_ids[3], w.a.student_ids[3]):  # not in a Python class
        code, _ = await _status(db_app, other, p_url(PY_VARS, "question"))
        assert code == 404
        code, _ = await _post_status(
            db_app,
            other,
            p_url(PY_VARS, "answer"),
            {"position": 1, "time_taken_ms": 1, **await answer_fields(db_app, mine)},
        )
        assert code == 404
    other_py = await _python_student(db_app, w.b.org_id, w.b.teacher_id)
    code, body = await _status(db_app, other_py, p_url(PY_VARS, "question"))
    assert code == 409 and body["code"] == "practice_locked"  # its own state, not school A's
    async with db_app.sessions() as session:
        owners = (await session.scalars(select(PracticeSession.student_id).distinct())).all()
    assert set(owners) <= {s}


async def test_code_items_spec_round_trip(db_app: DbApp) -> None:
    """Every stored code spec rebuilds as the schema (the helper the other tests rely on)."""
    await world(db_app)
    async with db_app.sessions() as session:
        items = (await session.scalars(select(Item).where(Item.type == ItemType.code))).all()
    assert items and all(code_spec(i.answer).tests for i in items)
    assert {i.kind for i in items} == {ItemKind.kp_question, ItemKind.practice}


async def test_an_answer_from_an_earlier_attempt_never_lands_in_the_new_one(db_app: DbApp) -> None:
    w = await world(db_app)
    s = await _python_student(db_app, w.a.org_id, w.a.teacher_id)
    await _pass_kps(db_app, s, PY_VARS)
    q1 = await get(db_app, s, p_url(PY_VARS, "question"))
    stale = {"position": 1, "time_taken_ms": 1, **await answer_fields(db_app, q1, correct=False)}
    failed = await post(db_app, s, p_url(PY_VARS, "answer"), stale)
    assert failed["session_status"] == "failed"
    q2 = await get(db_app, s, p_url(PY_VARS, "question"))  # Try again in one tab
    assert q2["session_id"] != q1["session_id"]
    # The other tab resends its answer to the first attempt: its stored result, nothing new.
    again = await post(db_app, s, p_url(PY_VARS, "answer"), stale)
    assert again["already_answered"] is True and again["correct"] is False
    # A different answer to the old attempt is stale.
    other = dict(stale, position=2)
    code, body = await _post_status(db_app, s, p_url(PY_VARS, "answer"), other)
    assert code == 409 and body["code"] == "stale_question"
    assert await count(db_app, Attempt, session_id=uuid.UUID(q2["session_id"])) == 0


async def test_a_resent_passing_answer_gets_its_result(db_app: DbApp) -> None:
    w = await world(db_app)
    s = await _python_student(db_app, w.a.org_id, w.a.teacher_id)
    await _pass_kps(db_app, s, PY_VARS)
    q = await get(db_app, s, p_url(PY_VARS, "question"))
    body = {"position": 1, "time_taken_ms": 1, **await answer_fields(db_app, q)}
    first = await post(db_app, s, p_url(PY_VARS, "answer"), body)
    assert first["concept_learned"] is True
    resent = await post(db_app, s, p_url(PY_VARS, "answer"), body)
    assert resent["already_answered"] is True and resent["correct"] is True
    assert resent["solution"]
    code, problem = await _post_status(db_app, s, p_url(PY_VARS, "answer"), dict(body, position=2))
    assert code == 409 and problem["code"] == "practice_passed"


async def test_multistep_item_in_a_kp_session_counts_once(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await post(db_app, s, url(DIST, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, DIST)
    path = url(DIST, "/kps/kp1")
    q = await get(db_app, s, f"{path}/question")
    async with db_app.sessions() as session:
        ms = await session.scalar(
            select(Item).where(
                Item.concept_id.in_(select(Concept.id).where(Concept.slug == DIST.split("/")[1])),
                Item.type == ItemType.multistep,
            )
        )
        assert ms is not None
        kp1 = await session.scalar(
            select(KnowledgePoint.id).where(
                KnowledgePoint.concept_id == ms.concept_id, KnowledgePoint.slug == "kp1"
            )
        )
        # No sample KP pool holds a multi-step item yet: move the practice problem into kp1's.
        await session.execute(
            update(Item).where(Item.id == ms.id).values(kind=ItemKind.kp_question, kp_id=kp1)
        )
        await session.execute(
            update(PracticeSession)
            .where(PracticeSession.id == uuid.UUID(q["session_id"]))
            .values(current_item_id=ms.id, current_seed=7)
        )
        await session.commit()
    q = await get(db_app, s, f"{path}/question")
    assert q["type"] == "multistep" and q["step"] == 0
    steps = len(q["steps"])
    for i in range(steps):
        res = await post(
            db_app,
            s,
            f"{path}/answer",
            {"position": 1, "time_taken_ms": 1, **await answer_fields(db_app, q)},
        )
        assert res["step"] == i
        if i < steps - 1:
            assert res["item_done"] is False and res["results"] == []
            assert res["session_status"] == "active" and res["solution"] is None
            q = await get(db_app, s, f"{path}/question")
            assert q["position"] == 1 and q["step"] == i + 1
    assert res["item_done"] is True and res["results"] == [True]
    nxt = await get(db_app, s, f"{path}/question")
    assert nxt["position"] == 2 and nxt["results"] == [True]


async def test_a_retired_practice_item_is_replaced_and_its_steps_discarded(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _pass_kps(db_app, s, DIST)
    q = await get(db_app, s, p_url(DIST, "question"))
    await _answer_step(db_app, s, DIST, q, correct=True)
    session_id = uuid.UUID(q["session_id"])
    assert await count(db_app, Attempt, session_id=session_id) == 1
    async with db_app.sessions() as session:
        replacement = Item(
            **{
                c.name: getattr(await session.get(Item, uuid.UUID(q["item_id"])), c.name)
                for c in Item.__table__.columns
                if c.name not in ("id", "slug", "position")
            },
            id=uuid.uuid4(),
            slug="practice-2",
            position=99,
        )
        session.add(replacement)
        await session.execute(
            update(Item)
            .where(Item.id == uuid.UUID(q["item_id"]))
            .values(retired_at=datetime.now(UTC))
        )
        await session.commit()
    again = await get(db_app, s, p_url(DIST, "question"))
    assert again["session_id"] == q["session_id"] and again["item_id"] == str(replacement.id)
    assert again["position"] == 1 and again["step"] == 0 and again["step_results"] == []
    assert await count(db_app, Attempt, session_id=session_id) == 0
