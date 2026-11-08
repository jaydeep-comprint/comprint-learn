"""The AI tutor (spec 009) on a real database, with a fake model client: routes, scoping, caps,
hints charged to attempts and XP, reserve/call/store races, after mode, safety and the kill
switch."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.ai import tutor_prompts as prompts
from app.ai.client import TutorUnavailable
from app.ai.eval import runner
from app.api.deps import CurrentUser, OrgScope
from app.core.config import get_settings
from app.models import (
    AppUser,
    Attempt,
    Item,
    PracticeSession,
    TutorKind,
    TutorMessage,
    TutorMode,
    TutorRole,
    TutorSession,
    TutorStatus,
    XpEvent,
)
from app.services import tutor as tutor_service
from app.services.tutor import ist_day
from tests.conftest import DbApp
from tests.learn_helpers import (
    DIST,
    LIN,
    SPEED,
    answer_check,
    answer_fields,
    answer_kp,
    answer_question,
    get,
    post,
    url,
    world,
)
from tests.review_helpers import make_due, review_path, seed_learned

pytestmark = pytest.mark.db


def tutor_url(q: dict[str, Any], tail: str = "") -> str:
    return f"/api/v1/tutor/{q['session_id']}/{q['position']}{tail}"


async def call(db: DbApp, user: uuid.UUID, method: str, path: str, **body: Any) -> tuple[int, Any]:
    if method == "GET":
        r = await db.client.get(path, headers=db.auth(user))
    else:
        r = await db.client.post(path, json=body, headers=db.auth(user))
    return r.status_code, r.json()


async def kp1_question(db: DbApp, user: uuid.UUID) -> dict[str, Any]:
    await post(db, user, url(DIST, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db, user, DIST)
    q: dict[str, Any] = await get(db, user, url(DIST, "/kps/kp1/question"))
    return q


async def answer(db: DbApp, user: uuid.UUID, q: dict[str, Any], *, correct: bool) -> Any:
    return await answer_question(db, user, url(DIST, "/kps/kp1"), q, correct=correct)


async def item_of(db: DbApp, q: dict[str, Any]) -> Item:
    async with db.sessions() as session:
        item = await session.get(Item, uuid.UUID(q["item_id"]))
        assert item is not None
        return item


async def rows(db: DbApp, user: uuid.UUID) -> list[TutorMessage]:
    async with db.sessions() as session:
        return list(
            (
                await session.scalars(
                    select(TutorMessage)
                    .where(TutorMessage.student_id == user)
                    .order_by(TutorMessage.created_at)
                )
            ).all()
        )


async def test_hints_in_order_charged_to_the_attempt_and_xp(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)

    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert code == 200
    assert thread["enabled"] and thread["mode"] == "before" and not thread["closed"]
    assert (thread["hints_left"], thread["next_rung"], thread["chat_left"]) == (3, 1, 10)
    assert thread["daily_left"] == 20 and thread["messages"] == []

    db_app.tutor.queue(
        ("ok", "Look at how the worked example adds each part of the walk."),
        ("ok", "Think about what a path length means."),
        ("ok", "Try it with easy numbers, like 1 m each way."),
    )
    for rung in (1, 2, 3):
        code, reply = await call(db_app, s, "POST", tutor_url(q, "/hint"), draft="12")
        assert code == 200, reply
        assert reply["message"]["rung"] == rung and reply["message"]["role"] == "tutor"
        assert reply["thread"]["hints_used"] == rung
    assert reply["thread"]["next_rung"] is None and reply["thread"]["hints_left"] == 0
    # Distance and displacement has no prerequisite: rung 2 has no link.
    assert reply["thread"]["messages"][3]["link"] is None
    code, body = await call(db_app, s, "POST", tutor_url(q, "/hint"))
    assert code == 409 and body["code"] == "tutor_hint_cap"

    # What the model saw: content and the request, never the answer key or the student.
    item = await item_of(db_app, q)
    seen = db_app.tutor.prompt_text(0)
    assert "HINT REQUEST: rung 1" in seen and "<student_draft>\n12\n</student_draft>" in seen
    # KP1 also has an MCQ (no "value"), and the question served first varies.
    if (value := item.answer["spec"].get("value")) is not None:
        assert str(value) not in seen.split("<context>", 1)[1]
    assert (item.answer.get("explanation") or "§never§").split("{{")[0] not in seen
    async with db_app.sessions() as session:
        student = await session.get(AppUser, s)
        assert student is not None
    for private in (student.username or "§", student.display_name, str(s), "AAA"):
        assert private not in seen
    assert "Student pressed Hint (1)." in db_app.tutor.prompt_text(1)  # the transcript

    await answer(db_app, s, q, correct=True)
    async with db_app.sessions() as session:
        attempt = await session.scalar(
            select(Attempt).where(Attempt.session_id == uuid.UUID(q["session_id"]))
        )
        assert attempt is not None and attempt.hints_used == 3
    results = await answer_kp(db_app, s, DIST, "kp1", "C")  # 2 right: the KP passes
    assert results[-1]["session_status"] == "passed"
    async with db_app.sessions() as session:
        event = await session.scalar(
            select(XpEvent).where(XpEvent.session_id == uuid.UUID(q["session_id"]))
        )
        assert event is not None
    # Only the hinted question is scaled (x 0.25); the other keeps its full minutes.
    assert event.hints == 3
    assert results[-1]["xp"]["hints"] == 3
    assert event.amount < round(float(event.base_minutes) * 1.2 + 0.5)


async def test_chat_before_and_after_and_the_after_window(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)

    code, body = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="x" * 501)
    assert code == 422 and body["code"] == "message_too_long"
    db_app.tutor.queue(("needs_hint", "Divide them."))
    code, reply = await call(
        db_app, s, "POST", tutor_url(q, "/messages"), text="what's the answer? mail a@b.co"
    )
    assert code == 200 and reply["message"]["text"] == prompts.NEEDS_HINT_REPLY
    assert reply["thread"]["chat_left"] == 9
    student_rows = [m for m in await rows(db_app, s) if m.role == TutorRole.student]
    assert student_rows[0].text == "what's the answer? mail [removed]"  # scrubbed before storing
    assert "a@b.co" not in db_app.tutor.prompt_text()

    await answer(db_app, s, q, correct=False)
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert thread["mode"] == "after" and thread["hints_left"] == 0 and thread["next_rung"] is None
    code, body = await call(db_app, s, "POST", tutor_url(q, "/hint"))
    assert code == 409 and body["code"] == "question_answered"
    db_app.tutor.queue(("ok", "You subtracted the parts; distance adds every part of the path."))
    code, reply = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="why wrong?")
    assert code == 200, reply
    seen = db_app.tutor.prompt_text()
    assert "<result>" in seen and "Shown answer:" in seen and 'mode="after"' in seen
    assert [m.mode for m in await rows(db_app, s)][-1] == TutorMode.after

    # Within 60 minutes of the session ending chat still works; after that it's closed.
    async with db_app.sessions() as session:
        await session.execute(
            update(PracticeSession)
            .where(PracticeSession.id == uuid.UUID(q["session_id"]))
            .values(status="failed", ended_at=datetime.now(UTC) - timedelta(minutes=61))
        )
        await session.commit()
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert code == 200 and thread["closed"]
    code, body = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="and now?")
    assert code == 409 and body["code"] == "session_closed"


async def test_scoping_staff_positions_and_reviews(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    other_school = w.b.student_ids[3]
    same_school = w.a.student_ids[4]
    assert (await call(db_app, other_school, "GET", tutor_url(q)))[0] == 404
    assert (await call(db_app, same_school, "GET", tutor_url(q)))[0] == 404
    for staff in (w.a.teacher_id, w.a.admin_id):
        assert (await call(db_app, staff, "GET", tutor_url(q)))[0] == 403
        assert (await call(db_app, staff, "POST", tutor_url(q, "/hint")))[0] == 403
    ahead = {**q, "position": q["position"] + 1}
    assert (await call(db_app, s, "GET", tutor_url(ahead)))[0] == 404
    bogus = {**q, "session_id": str(uuid.uuid4())}
    assert (await call(db_app, s, "GET", tutor_url(bogus)))[0] == 404

    # Scheduled reviews have no tutor.
    learner = w.a.student_ids[4]
    await seed_learned(db_app, w.a.org_id, learner, [DIST])
    await make_due(db_app, learner, DIST)
    rq = await get(db_app, learner, f"{review_path(DIST)}/question")
    code, body = await call(db_app, learner, "GET", tutor_url(rq))
    assert code == 409 and body["code"] == "tutor_not_here"


async def test_daily_cap_and_errors_not_counted(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)

    db_app.tutor.queue(TutorUnavailable("timeout"))
    code, body = await call(db_app, s, "POST", tutor_url(q, "/hint"))
    assert code == 503 and body["code"] == "tutor_unavailable"
    [row] = await rows(db_app, s)
    assert row.status == TutorStatus.error
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert thread["daily_left"] == 20 and thread["hints_used"] == 0 and thread["messages"] == []

    # 19 requests used elsewhere today (another thread); the 20th works, the 21st is refused.
    async with db_app.sessions() as session:
        ps = await session.get(PracticeSession, uuid.UUID(q["session_id"]))
        assert ps is not None
        other = TutorSession(
            org_id=w.a.org_id,
            student_id=s,
            practice_session_id=ps.id,
            position=99,
            item_id=uuid.UUID(q["item_id"]),
            item_version=1,
            seed=None,
        )
        session.add(other)
        await session.flush()
        for _ in range(19):
            session.add(
                TutorMessage(
                    org_id=w.a.org_id,
                    tutor_session_id=other.id,
                    student_id=s,
                    role=TutorRole.student,
                    kind=TutorKind.chat,
                    mode=TutorMode.before,
                    status=TutorStatus.ok,
                    day=ist_day(datetime.now(UTC)),
                )
            )
        await session.commit()
    code, reply = await call(db_app, s, "POST", tutor_url(q, "/hint"))
    assert code == 200 and reply["thread"]["daily_left"] == 0
    code, body = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="hi")
    assert code == 429 and body["code"] == "tutor_daily_cap" and "resets_at" in body


async def test_busy_and_question_answered_during_a_pending_hint(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    db_app.tutor.gate = asyncio.Event()
    pending = asyncio.create_task(call(db_app, s, "POST", tutor_url(q, "/hint")))
    await asyncio.wait_for(db_app.tutor.started.wait(), 10)

    code, body = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="hello?")
    assert code == 409 and body["code"] == "tutor_busy"
    # The answer lands while the hint is in flight: it doesn't include that hint.
    body = {"position": q["position"], "time_taken_ms": 3000} | await answer_fields(db_app, q)
    await post(db_app, s, url(DIST, "/kps/kp1/answer"), body)
    db_app.tutor.gate.set()
    code, body = await pending
    assert code == 409 and body["code"] == "question_answered"

    async with db_app.sessions() as session:
        attempt = await session.scalar(
            select(Attempt).where(Attempt.session_id == uuid.UUID(q["session_id"]))
        )
        thread = await session.scalar(select(TutorSession))
    assert attempt is not None and attempt.hints_used == 0
    assert thread is not None and thread.hints_used == 0
    assert {m.status for m in await rows(db_app, s)} == {TutorStatus.late}


async def test_parallel_requests_on_two_threads_respect_the_daily_cap(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    async with db_app.sessions() as session:
        ps = await session.get(PracticeSession, uuid.UUID(q["session_id"]))
        assert ps is not None
        seed = TutorSession(
            org_id=w.a.org_id,
            student_id=s,
            practice_session_id=ps.id,
            position=99,
            item_id=ps.current_item_id,
            item_version=1,
        )
        session.add(seed)
        await session.flush()
        for _ in range(19):
            session.add(
                TutorMessage(
                    org_id=w.a.org_id,
                    tutor_session_id=seed.id,
                    student_id=s,
                    role=TutorRole.student,
                    kind=TutorKind.chat,
                    mode=TutorMode.before,
                    status=TutorStatus.ok,
                    day=ist_day(datetime.now(UTC)),
                )
            )
        await session.commit()
    # 19 used on another thread; race a hint and a chat: the advisory lock lets one through.
    results = await asyncio.gather(
        call(db_app, s, "POST", tutor_url(q, "/hint")),
        call(db_app, s, "POST", tutor_url(q, "/messages"), text="what does 'east' mean?"),
    )
    codes = sorted(code for code, _ in results)
    assert codes[0] == 200 and codes[1] in (409, 429)  # busy or capped, never both through


async def test_safety_reply_and_flag(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    code, reply = await call(
        db_app, s, "POST", tutor_url(q, "/messages"), text="everyone at school bullies me"
    )
    assert code == 200 and reply["message"]["text"] == prompts.SAFETY_REPLY
    assert db_app.tutor.requests == []  # keyword hit: no model call
    tutor_row = next(m for m in await rows(db_app, s) if m.role == TutorRole.tutor)
    assert tutor_row.flagged and tutor_row.status == TutorStatus.safety
    assert reply["thread"]["daily_left"] == 19 and reply["thread"]["chat_left"] == 9


async def test_kill_switch(db_app: DbApp, monkeypatch: pytest.MonkeyPatch) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    monkeypatch.setenv("TUTOR_ENABLED", "false")
    get_settings.cache_clear()
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert code == 200 and thread["enabled"] is False
    code, body = await call(db_app, s, "POST", tutor_url(q, "/hint"))
    assert code == 503 and body["code"] == "tutor_unavailable"
    assert await rows(db_app, s) == []


async def test_new_thread_after_an_item_swap(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    db_app.tutor.queue(("ok", "Look at the worked example."))
    assert (await call(db_app, s, "POST", tutor_url(q, "/hint")))[0] == 200
    async with db_app.sessions() as session:  # what practice.py does for a retired item
        ps = await session.get(PracticeSession, uuid.UUID(q["session_id"]))
        assert ps is not None
        other = await session.scalar(
            select(Item.id).where(
                Item.kp_id == (await item_of(db_app, q)).kp_id, Item.id != ps.current_item_id
            )
        )
        ps.current_item_id = other
        ps.current_seed = 7
        await session.commit()
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert code == 200 and thread["hints_used"] == 0 and thread["messages"] == []


async def test_rung_2_links_the_key_prerequisite(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST, LIN])
    await post(db_app, s, url(SPEED, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, SPEED)
    q = await get(db_app, s, url(SPEED, "/kps/kp1/question"))
    db_app.tutor.queue(("ok", "a"), ("ok", "Think about displacement over a time."))
    await call(db_app, s, "POST", tutor_url(q, "/hint"))
    code, reply = await call(db_app, s, "POST", tutor_url(q, "/hint"))
    assert code == 200
    assert reply["message"]["link"] == {"id": DIST, "title": "Distance and displacement"}
    assert "<hint_prerequisite>Distance and displacement" in db_app.tutor.prompt_text()


async def test_purge_nulls_old_text_and_keeps_counts(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    db_app.tutor.queue(("ok", "Read the question again."))
    await call(db_app, s, "POST", tutor_url(q, "/messages"), text="what does east mean?")
    async with db_app.sessions() as session:
        await session.execute(
            update(TutorMessage).values(created_at=datetime.now(UTC) - timedelta(days=181))
        )
        await session.commit()
        assert await tutor_service.purge_text(session, datetime.now(UTC)) == 2
        assert await tutor_service.purge_text(session, datetime.now(UTC)) == 0  # idempotent
    purged = await rows(db_app, s)
    assert [m.text for m in purged] == [None, None]
    assert all(m.purged_at is not None for m in purged)
    assert [m.output_tokens for m in purged if m.role == TutorRole.tutor] == [20]
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert code == 200 and thread["chat_left"] == 9  # counts stay


async def test_flagged_lists_ids_only(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    await call(db_app, s, "POST", tutor_url(q, "/messages"), text="I want to hurt myself")
    async with db_app.sessions() as session:
        [row] = await tutor_service.flagged(session, "aaa")
        assert await tutor_service.flagged(session, "BBB") == []
    assert (row.org_code, row.student_id, row.text) == ("AAA", s, "I want to hurt myself")


async def test_every_eval_case_builds_a_context(db_app: DbApp) -> None:
    """The eval's cases point at real items and valid attempts (no model call)."""
    await world(db_app)
    async with db_app.sessions() as session:
        for case in runner.load_cases():
            item, ctx = await runner.build_case_context(session, case)
            assert ctx.text.startswith("<context>"), case.id
            assert runner.true_answer(item, case.seed), case.id
            if ctx.mode == "before" and ctx.item_type in ("numeric", "expression", "multistep"):
                assert ctx.facts.numbers or ctx.facts.expressions, case.id
    assert len(runner.load_cases()) >= 30


async def _thread_row(db: DbApp, q: dict[str, Any]) -> TutorSession:
    async with db.sessions() as session:
        thread = await session.scalar(
            select(TutorSession).where(
                TutorSession.practice_session_id == uuid.UUID(q["session_id"]),
                TutorSession.position == q["position"],
            )
        )
        assert thread is not None
        return thread


async def test_chat_cap_per_thread(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    assert (await call(db_app, s, "POST", tutor_url(q, "/messages"), text="hi"))[0] == 200
    async with db_app.sessions() as session:
        await session.execute(update(TutorSession).values(chat_count=10))
        await session.commit()
    code, body = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="again?")
    assert code == 409 and body["code"] == "tutor_chat_cap"
    code, thread = await call(db_app, s, "GET", tutor_url(q))
    assert thread["chat_left"] == 0


async def test_a_lost_pending_request_does_not_block_the_thread(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    db_app.tutor.queue(("ok", "Look at the worked example."))
    assert (await call(db_app, s, "POST", tutor_url(q, "/hint")))[0] == 200
    thread = await _thread_row(db_app, q)
    async with db_app.sessions() as session:  # a request lost mid-call (worker restart)
        session.add(
            TutorMessage(
                org_id=w.a.org_id,
                tutor_session_id=thread.id,
                student_id=s,
                role=TutorRole.student,
                kind=TutorKind.chat,
                mode=TutorMode.before,
                status=TutorStatus.pending,
                text="lost",
                day=ist_day(datetime.now(UTC)),
                created_at=datetime.now(UTC) - timedelta(minutes=3),
            )
        )
        await session.commit()
    code, thread_out = await call(db_app, s, "GET", tutor_url(q))
    assert thread_out["daily_left"] == 19  # the lost row isn't counted
    code, reply = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="what is east?")
    assert code == 200, reply  # not `tutor_busy`
    statuses = {m.text: m.status for m in await rows(db_app, s) if m.role == TutorRole.student}
    assert statuses["lost"] == TutorStatus.error


async def test_an_unexpected_error_closes_the_pending_row(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    db_app.tutor.queue(RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        await call(db_app, s, "POST", tutor_url(q, "/hint"))
    [row] = await rows(db_app, s)
    assert row.status == TutorStatus.error
    db_app.tutor.queue(("ok", "Look at the worked example."))
    assert (await call(db_app, s, "POST", tutor_url(q, "/hint")))[0] == 200


async def test_hints_for_attempt_subtracts_hints_already_on_the_position(db_app: DbApp) -> None:
    """A multi-step item: hints before step 1 land on step 1's row, later ones on step 2's."""
    w = await world(db_app)
    s = w.physics_student
    q = await kp1_question(db_app, s)
    db_app.tutor.queue(("ok", "a"), ("ok", "b"))
    await call(db_app, s, "POST", tutor_url(q, "/hint"))
    await call(db_app, s, "POST", tutor_url(q, "/hint"))
    async with db_app.sessions() as session:
        ps = await session.get(PracticeSession, uuid.UUID(q["session_id"]))
        assert ps is not None
        user = await session.get(AppUser, s)
        assert user is not None
        scope = OrgScope(session, CurrentUser(s, w.a.org_id, user.role, False, False))
        assert ps.current_item_id is not None
        assert (
            await tutor_service.hints_for_attempt(scope, ps, ps.current_item_id, ps.current_seed)
            == 2
        )
        # Pretend step 0 was answered carrying one of them: the next row gets the other.
        session.add(
            Attempt(
                org_id=w.a.org_id,
                student_id=s,
                item_id=ps.current_item_id,
                item_version=1,
                context="kp",
                seed=ps.current_seed,
                response={"raw": "1"},
                correct=False,
                time_taken_ms=10_000,
                hints_used=1,
                session_id=ps.id,
                position=ps.current_position,
                step=0,
            )
        )
        await session.flush()
        assert (
            await tutor_service.hints_for_attempt(scope, ps, ps.current_item_id, ps.current_seed)
            == 1
        )
        await session.rollback()
