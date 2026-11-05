"""Review cards, Today's reviews, review sessions, brush-ups as reviews and implicit credit
(spec 007) on a real database."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from app.models import (
    ConceptPrereq,
    Item,
    KpProgress,
    KpStatus,
    ReviewDueReason,
    ReviewSource,
    XpEvent,
    XpReason,
)
from app.models.content import ItemKind
from app.services import srs
from tests.conftest import DbApp
from tests.learn_helpers import (
    ACCEL,
    DIST,
    LIN,
    MATHS,
    SPEED,
    answer_check,
    answer_kp,
    answer_question,
    get,
    learn_concept,
    post,
    url,
    world,
)
from tests.review_helpers import (
    REVIEWS,
    card,
    concept_status,
    do_review,
    logs,
    make_due,
    offered_refs,
    queue,
    review_path,
    seed_learned,
    set_card,
)

pytestmark = pytest.mark.db

PAIR_ALG = f"{MATHS}/pair-of-linear-equations-algebraic"
PAIR_GRAPH = f"{MATHS}/pair-of-linear-equations-graphical"
ALL_SIX = [DIST, SPEED, ACCEL, LIN, PAIR_ALG, PAIR_GRAPH]


async def _status(db: DbApp, user: uuid.UUID, path: str) -> tuple[int, dict[str, Any]]:
    r = await db.client.get(path, headers=db.auth(user))
    return r.status_code, r.json()


async def _cooldown_over(db: DbApp, user: uuid.UUID) -> None:
    async with db.sessions() as session:
        await session.execute(
            update(KpProgress)
            .where(KpProgress.student_id == user, KpProgress.status == KpStatus.failed)
            .values(reopen_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def test_learning_creates_a_card_not_due_today(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    q = await queue(db_app, s)
    assert q["has_cards"] is False and q["offered"] == []
    await learn_concept(db_app, s, DIST)
    c = await card(db_app, s, DIST)
    assert c is not None and c.reps == 1 and c.due_reason == ReviewDueReason.schedule
    assert srs.ist_day(c.due) > srs.ist_day(datetime.now(UTC))
    assert [entry.source for entry in await logs(db_app, s, DIST)] == [ReviewSource.learned]
    q = await queue(db_app, s)
    assert q["has_cards"] is True and q["offered"] == [] and q["done_today"] == 0
    assert q["next_due_on"] == srs.ist_day(c.due).isoformat()
    code, body = await _status(db_app, s, f"{review_path(DIST)}/question")
    assert code == 409 and body["code"] == "review_not_due"


async def test_due_review_passes_and_reschedules_with_xp(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST])
    await make_due(db_app, s, DIST)
    q = await queue(db_app, s)
    assert offered_refs(q) == [DIST]
    assert q["offered"][0]["reason"] == "schedule" and q["offered"][0]["active"] is False
    first = await get(db_app, s, f"{review_path(DIST)}/question")
    assert first["position"] == 1 and "display_answer" not in first
    again = await get(db_app, s, f"{review_path(DIST)}/question")
    assert again["item_id"] == first["item_id"]  # reload: same question
    assert (await queue(db_app, s))["offered"][0]["active"] is True
    result = await do_review(db_app, s, DIST, "CCC")
    assert result["session_status"] == "passed"
    assert result["review"]["rating"] == "good" and result["review"]["relearn"] is False
    next_due = result["review"]["next_due"]
    assert next_due > srs.ist_day(datetime.now(UTC)).isoformat()
    assert result["xp"]["amount"] > 0
    async with db_app.sessions() as session:
        reasons = (
            await session.scalars(select(XpEvent.reason).where(XpEvent.student_id == s))
        ).all()
    assert list(reasons) == [XpReason.review]
    review_logs = [e for e in await logs(db_app, s, DIST) if e.source == ReviewSource.review]
    assert len(review_logs) == 1 and review_logs[0].due_reason == ReviewDueReason.schedule
    q = await queue(db_app, s)
    assert q["done_today"] == 1 and q["offered"] == []


async def test_daily_cap_and_quiz_miss_past_the_cap(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, ALL_SIX)
    # No implicit credit here: a passed review crediting another due card would fire its Good
    # and take it off today's list (content is re-imported for every test).
    async with db_app.sessions() as session:
        await session.execute(delete(ConceptPrereq))
        await session.commit()
    for ref in ALL_SIX:
        await make_due(db_app, s, ref)
    q = await queue(db_app, s)
    assert len(q["offered"]) == 5 and q["more_due"] == 1 and q["cap"] == 5
    subjects = [o["subject"] for o in q["offered"]]
    assert subjects[:4] == ["physics", "maths", "physics", "maths"] or subjects[:4] == [
        "maths",
        "physics",
        "maths",
        "physics",
    ]  # interleaved by subject
    hidden = next(r for r in ALL_SIX if r not in offered_refs(q))
    for ref in offered_refs(q):
        await do_review(db_app, s, ref, "CCC")
    q = await queue(db_app, s)
    assert q["done_today"] == 5 and q["offered"] == []
    assert q["next_due_on"] == (srs.ist_day(datetime.now(UTC)) + timedelta(days=1)).isoformat()
    code, body = await _status(db_app, s, f"{review_path(hidden)}/question")
    assert code == 409 and body["code"] == "review_cap"
    # A quiz-miss card is outside the cap, and its review doesn't count against it.
    await set_card(db_app, s, hidden, due_reason=ReviewDueReason.quiz_miss)
    q = await queue(db_app, s)
    assert offered_refs(q) == [hidden] and q["offered"][0]["reason"] == "quiz_miss"
    result = await do_review(db_app, s, hidden, "CCC")
    assert result["session_status"] == "passed"
    c = await card(db_app, s, hidden)
    assert c is not None and c.due_reason == ReviewDueReason.schedule
    assert (await queue(db_app, s))["done_today"] == 5


async def test_fail_once_stays_learned_fail_again_relearns(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await learn_concept(db_app, s, DIST)
    await make_due(db_app, s, DIST)
    first = await do_review(db_app, s, DIST, "WWW")
    assert first["session_status"] == "failed"
    assert first["review"] == {
        "rating": "again",
        "next_due": first["review"]["next_due"],
        "relearn": False,
    }
    assert (
        first["review"]["next_due"]
        >= (srs.ist_day(datetime.now(UTC)) + timedelta(days=1)).isoformat()
    )
    assert await concept_status(db_app, s, DIST) == "learned"
    c = await card(db_app, s, DIST)
    assert c is not None and c.consecutive_fails == 1 and c.lapses == 1
    await make_due(db_app, s, DIST)
    second = await do_review(db_app, s, DIST, "WWW")
    assert second["review"]["relearn"] is True and second["review"]["next_due"] is None
    assert await concept_status(db_app, s, DIST) == "in_progress"
    lesson = await get(db_app, s, url(DIST))
    assert [k["status"] for k in lesson["kps"]] == ["not_started"] * len(lesson["kps"])
    assert offered_refs(await queue(db_app, s)) == []  # not offered while relearning
    # Learned again: the card is reviewed Good, with the fail count reset.
    await learn_concept(db_app, s, DIST)
    c = await card(db_app, s, DIST)
    assert c is not None and c.consecutive_fails == 0
    assert (await logs(db_app, s, DIST))[-1].source == ReviewSource.relearned


async def test_a_pass_between_fails_resets_the_count(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST])
    for pattern in ("WWW", "CCC", "WWW"):
        await make_due(db_app, s, DIST)
        await do_review(db_app, s, DIST, pattern)
    assert await concept_status(db_app, s, DIST) == "learned"
    c = await card(db_app, s, DIST)
    assert c is not None and c.consecutive_fails == 1


async def test_brushup_updates_the_prereq_card_and_hides_it(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST, LIN])
    await post(db_app, s, url(SPEED, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db_app, s, SPEED)
    await answer_kp(db_app, s, SPEED, "kp1", "WWW")
    await _cooldown_over(db_app, s)
    second = await answer_kp(db_app, s, SPEED, "kp1", "WWW")
    rid = second[-1]["remediations"][0]["id"]
    prereq = second[-1]["remediations"][0]["prereq"]["id"]
    await make_due(db_app, s, prereq)
    assert prereq not in offered_refs(await queue(db_app, s))  # the brush-up shows instead
    code, body = await _status(db_app, s, f"{review_path(prereq)}/question")
    assert code == 409 and body["code"] == "review_not_due"
    before = await card(db_app, s, prereq)
    assert before is not None
    path = f"/api/v1/learn/remediations/{rid}"
    for _ in range(3):
        q = await get(db_app, s, f"{path}/question")
        res = await answer_question(db_app, s, path, q)
    assert res["session_status"] == "passed"
    after = await card(db_app, s, prereq)
    assert after is not None and after.reps == before.reps + 1 and after.due > before.due
    brushups = [e for e in await logs(db_app, s, prereq) if e.source == ReviewSource.brushup]
    assert len(brushups) == 1 and brushups[0].rating == 3  # Good


async def test_implicit_credit_postpones_a_due_prerequisite(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST, LIN])
    now = datetime.now(UTC)
    # DIST is due (earliness 1) and already holds some credit; SPEED's KPs add 3 x 0.7/3.
    await set_card(db_app, s, DIST, last_review=now - timedelta(days=4), due=now, credit=0.4)
    await learn_concept(db_app, s, SPEED)
    c = await card(db_app, s, DIST)
    assert c is not None and c.credit == 0.0 and c.due > now + timedelta(hours=12)
    implicit = [e for e in await logs(db_app, s, DIST) if e.source == ReviewSource.implicit]
    assert implicit and implicit[-1].rating == 3
    assert DIST not in offered_refs(await queue(db_app, s))
    # One level only: SPEED's own prerequisites' prerequisites get nothing (DIST has none),
    # and LIN (weight 0.2) got 3 x 0.2/3 credit without firing.
    lin = await card(db_app, s, LIN)
    assert lin is not None and 0 < lin.credit < 1


async def test_no_implicit_credit_after_a_failed_review(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST, LIN])
    now = datetime.now(UTC)
    await set_card(
        db_app, s, DIST, last_review=now - timedelta(days=4), due=now, credit=0.9,
        consecutive_fails=1,
    )  # fmt: skip
    await learn_concept(db_app, s, SPEED)
    c = await card(db_app, s, DIST)
    assert c is not None and c.credit == pytest.approx(0.9)
    assert not [e for e in await logs(db_app, s, DIST) if e.source == ReviewSource.implicit]


async def test_reviews_are_students_only_and_scoped(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST])
    await make_due(db_app, s, DIST)
    for staff in (w.a.teacher_id, w.a.admin_id):
        code, _ = await _status(db_app, staff, REVIEWS)
        assert code == 403
        code, _ = await _status(db_app, staff, f"{review_path(DIST)}/question")
        assert code == 403
    other = w.b.student_ids[3]  # another school's student: no card of theirs is due
    code, body = await _status(db_app, other, f"{review_path(DIST)}/question")
    assert code == 409 and body["code"] == "review_not_due"
    code, _ = await _status(db_app, s, f"{REVIEWS}/{MATHS}/nope/question")
    assert code == 404


async def test_roster_reviews_due(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST, LIN])
    await make_due(db_app, s, DIST)
    await set_card(db_app, s, LIN, due_reason=ReviewDueReason.quiz_miss)
    rows = await get(db_app, w.a.teacher_id, f"/api/v1/classes/{w.a.class_ids[1]}/students")
    me = next(r for r in rows if r["id"] == str(s))
    assert me["reviews_due"] == 2 and me["last_quiz"] is None
    assert all(r["reviews_due"] == 0 for r in rows if r["id"] != str(s))


async def test_a_card_with_no_questions_left_is_never_offered(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await seed_learned(db_app, w.a.org_id, s, [DIST])
    await make_due(db_app, s, DIST)
    cid = (await card(db_app, s, DIST)).concept_id  # type: ignore[union-attr]
    async with db_app.sessions() as session:
        await session.execute(
            update(Item)
            .where(Item.concept_id == cid, Item.kind == ItemKind.kp_question)
            .values(retired_at=datetime.now(UTC))
        )
        await session.commit()
    assert offered_refs(await queue(db_app, s)) == []
    rows = await get(db_app, w.a.teacher_id, f"/api/v1/classes/{w.a.class_ids[1]}/students")
    assert next(r for r in rows if r["id"] == str(s))["reviews_due"] == 0
