"""XP awards, daily goals, streaks, leaderboards and roster stats (spec 008) on a real database."""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from app.models import (
    AppUser,
    Concept,
    Enrollment,
    Item,
    KnowledgePoint,
    KpProgress,
    KpStatus,
    PracticeSession,
    SessionStatus,
    Subject,
    UserStatus,
    XpDay,
    XpEvent,
    XpGrade,
    XpReason,
)
from app.services.xp import ist_date, ist_week_start
from tests.conftest import DbApp
from tests.learn_helpers import (
    DIST,
    answer_check,
    answer_fields,
    answer_kp,
    answer_question,
    count,
    get,
    learn_concept,
    pass_practice,
    post,
    url,
    world,
)

pytestmark = pytest.mark.db


def q_url(ref: str, kp: str) -> str:
    return url(ref, f"/kps/{kp}/question")


def a_url(ref: str, kp: str) -> str:
    return url(ref, f"/kps/{kp}/answer")


async def _open_lesson(db: DbApp, user: uuid.UUID, ref: str) -> None:
    await post(db, user, url(ref, "/progress"), {"step": "intro", "active_seconds": 5})
    await answer_check(db, user, ref)


async def _events(db: DbApp, user: uuid.UUID) -> list[XpEvent]:
    async with db.sessions() as session:
        rows = await session.scalars(
            select(XpEvent).where(XpEvent.student_id == user).order_by(XpEvent.id)
        )
        return list(rows.all())


async def _days(db: DbApp, user: uuid.UUID) -> dict[Subject, XpDay]:
    async with db.sessions() as session:
        rows = await session.scalars(select(XpDay).where(XpDay.student_id == user))
        return {r.subject: r for r in rows.all()}


async def _slow_down(db: DbApp, user: uuid.UUID) -> None:
    """Pretend the current question was served 10 minutes ago (answers aren't rushed)."""
    async with db.sessions() as session:
        await session.execute(
            update(PracticeSession)
            .where(
                PracticeSession.student_id == user,
                PracticeSession.status == SessionStatus.active,
            )
            .values(current_served_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await session.commit()


async def _cooldown_over(db: DbApp, user: uuid.UUID) -> None:
    async with db.sessions() as session:
        await session.execute(
            update(KpProgress)
            .where(KpProgress.student_id == user, KpProgress.status == KpStatus.failed)
            .values(reopen_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def _patch_class(db: DbApp, teacher: uuid.UUID, class_id: uuid.UUID, **body: Any) -> Any:
    r = await db.client.patch(f"/api/v1/classes/{class_id}", json=body, headers=db.auth(teacher))
    assert r.status_code == 200, r.text
    return r.json()


async def _put_goal(db: DbApp, user: uuid.UUID, subject: str, goal: int | None) -> Any:
    return await db.client.put(
        f"/api/v1/me/goals/{subject}", json={"goal": goal}, headers=db.auth(user)
    )


async def _enroll(db: DbApp, org_id: uuid.UUID, class_id: uuid.UUID, user: uuid.UUID) -> None:
    async with db.sessions() as session:
        session.add(Enrollment(org_id=org_id, class_id=class_id, student_id=user))
        await session.commit()


# --- awards ---------------------------------------------------------------------------------------


async def test_kp_pass_awards_once_with_day_rows_for_every_goal_subject(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _enroll(db_app, w.a.org_id, w.a.class_ids[0], s)  # also in the maths class
    await _open_lesson(db_app, s, DIST)
    path = url(DIST, "/kps/kp1")
    first = await answer_question(db_app, s, path, await get(db_app, s, q_url(DIST, "kp1")))
    assert first["session_status"] == "active" and first["xp"] is None
    q = await get(db_app, s, q_url(DIST, "kp1"))
    body = {"position": q["position"], "time_taken_ms": 3000, **await answer_fields(db_app, q)}
    ended = await post(db_app, s, a_url(DIST, "kp1"), body)
    assert ended["session_status"] == "passed"
    award = ended["xp"]
    assert award["grade"] == "perfect" and award["amount"] >= 1 and award["hints"] == 0

    [event] = await _events(db_app, s)
    assert (event.reason, event.subject, event.grade) == (
        XpReason.kp,
        Subject.physics,
        XpGrade.perfect,
    )
    assert event.answered == 2 and event.amount == award["amount"]
    assert event.day == ist_date(datetime.now(UTC))
    assert Decimal(award["base_minutes"]) == event.base_minutes
    days = await _days(db_app, s)
    assert set(days) == {Subject.physics, Subject.maths}
    assert (days[Subject.physics].xp, days[Subject.physics].goal) == (award["amount"], 15)
    assert (days[Subject.maths].xp, days[Subject.maths].goal) == (0, 15)

    resent = await post(db_app, s, a_url(DIST, "kp1"), body)
    assert resent["already_answered"] is True and resent["xp"] == award
    assert len(await _events(db_app, s)) == 1


async def test_two_answers_ending_a_session_at_once_award_once(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    await answer_kp(db_app, s, DIST, "kp1", "C")
    q = await get(db_app, s, q_url(DIST, "kp1"))
    body = {"position": q["position"], "time_taken_ms": 3000, **await answer_fields(db_app, q)}
    r1, r2 = await asyncio.gather(
        db_app.client.post(a_url(DIST, "kp1"), json=body, headers=db_app.auth(s)),
        db_app.client.post(a_url(DIST, "kp1"), json=body, headers=db_app.auth(s)),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["xp"] == r2.json()["xp"] is not None
    assert len(await _events(db_app, s)) == 1


async def test_rushed_fail_costs_xp_and_is_shown_as_zero(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    results = await answer_kp(db_app, s, DIST, "kp1", "WWW")  # answered in milliseconds
    assert results[-1]["session_status"] == "failed"
    award = results[-1]["xp"]
    assert award["grade"] == "rushed" and award["amount"] <= -1
    assert (await _days(db_app, s))[Subject.physics].xp == award["amount"]
    summary = await get(db_app, s, "/api/v1/me/xp")
    assert summary["today"] == [{"subject": "physics", "xp": 0, "goal": 15, "met": False}]
    assert summary["week_xp"] == summary["total_xp"] == 0


async def test_slow_fail_is_poor_and_still_writes_a_zero_event(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    last: dict[str, Any] = {}
    for _ in range(3):
        q = await get(db_app, s, q_url(DIST, "kp1"))
        await _slow_down(db_app, s)
        body = {
            "position": q["position"],
            "time_taken_ms": 600_000,
            **await answer_fields(db_app, q, correct=False),
        }
        last = await post(db_app, s, a_url(DIST, "kp1"), body)
    assert last["session_status"] == "failed"
    assert last["xp"]["amount"] == 0 and last["xp"]["grade"] == "poor"
    [event] = await _events(db_app, s)
    assert (event.amount, event.rushed_count, event.answered) == (0, 0, 3)


async def test_practice_and_brush_up_awards(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    last = await learn_concept(db_app, s, DIST)  # 3 KPs, then the practice pass
    assert last["xp"]["grade"] == "perfect"
    events = await _events(db_app, s)
    assert [e.reason for e in events] == [XpReason.kp] * 3 + [XpReason.practice]
    async with db_app.sessions() as session:
        dist_id = await session.scalar(
            select(Concept.id).where(Concept.slug == "distance-and-displacement")
        )
    assert all(e.concept_id == dist_id for e in events)

    # A brush-up of DIST from the speed lesson goes to DIST (the prerequisite).
    speed = "physics-9-10/speed-and-velocity"
    await learn_concept(db_app, s, "maths-9-10/linear-equations-two-variables")
    await _open_lesson(db_app, s, speed)
    await answer_kp(db_app, s, speed, "kp1", "WWW")
    await _cooldown_over(db_app, s)
    second = await answer_kp(db_app, s, speed, "kp1", "WWW")
    rem = next(r for r in second[-1]["remediations"] if r["prereq"]["id"] == DIST)
    res: dict[str, Any] = {}
    for _ in range(3):
        q = await get(db_app, s, f"/api/v1/learn/remediations/{rem['id']}/question")
        body = {"position": q["position"], "time_taken_ms": 100, **await answer_fields(db_app, q)}
        res = await post(db_app, s, f"/api/v1/learn/remediations/{rem['id']}/answer", body)
    assert res["session_status"] == "passed" and res["xp"]["grade"] == "perfect"
    review = (await _events(db_app, s))[-1]
    assert (review.reason, review.concept_id, review.subject) == (
        XpReason.remediation,
        dist_id,
        Subject.physics,
    )


async def test_side_effect_closes_previews_and_practise_again_earn_nothing(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _open_lesson(db_app, s, DIST)
    await get(db_app, s, q_url(DIST, "kp1"))  # session active
    async with db_app.sessions() as session:
        kp1 = select(KnowledgePoint.id).where(
            KnowledgePoint.slug == "kp1",
            KnowledgePoint.concept_id.in_(
                select(Concept.id).where(Concept.slug == "distance-and-displacement")
            ),
        )
        await session.execute(
            update(Item).where(Item.kp_id.in_(kp1)).values(retired_at=datetime.now(UTC))
        )
        await session.commit()
    r = await db_app.client.get(q_url(DIST, "kp1"), headers=db_app.auth(s))
    assert r.status_code == 409 and r.json()["code"] == "kp_passed"  # closed by a read
    assert await count(db_app, XpEvent) == 0

    t = w.a.teacher_id
    q = await get(db_app, t, q_url(DIST, "kp2"))
    preview = {
        "position": 1,
        "time_taken_ms": 1,
        "item_id": q["item_id"],
        "seed": q["preview_seed"],
    }
    res = await post(db_app, t, a_url(DIST, "kp2"), preview | await answer_fields(db_app, q))
    assert res.get("xp") is None
    assert await count(db_app, XpEvent) == 0

    other = w.a.student_ids[4]  # another physics student
    await learn_concept(db_app, other, DIST)
    before = await count(db_app, XpEvent)
    q = await get(db_app, other, url(DIST, "/practice/question?again=true"))
    body = {"position": 1, "time_taken_ms": 1, "item_id": q["item_id"], "seed": q["preview_seed"]}
    res = await post(
        db_app,
        other,
        url(DIST, "/practice/answer?again=true"),
        body | await answer_fields(db_app, q),
    )
    assert res.get("xp") is None
    assert await count(db_app, XpEvent) == before


# --- goals ----------------------------------------------------------------------------------------


async def test_goal_errors_and_own_goal(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    for bad in (7, 0, 65):
        r = await _put_goal(db_app, s, "physics", bad)
        assert r.status_code == 422 and r.json()["code"] == "goal_invalid"
    r = await _put_goal(db_app, s, "maths", 20)
    assert r.status_code == 422 and r.json()["code"] == "no_class_for_subject"
    r = await _put_goal(db_app, s, "physics", 10)
    assert r.status_code == 422 and r.json() == {
        "code": "goal_below_class",
        "message": "Your teacher's goal is 15 XP; pick 15 or more.",
    }
    r = await _put_goal(db_app, s, "physics", 25)
    assert r.status_code == 200
    assert r.json()["goals"] == [
        {"subject": "physics", "class_goal": 15, "own_goal": 25, "effective": 25}
    ]
    r = await _put_goal(db_app, s, "physics", None)
    assert r.json()["goals"][0] == {
        "subject": "physics",
        "class_goal": 15,
        "own_goal": None,
        "effective": 15,
    }
    for path in ("/api/v1/me/xp",):
        r = await db_app.client.get(path, headers=db_app.auth(w.a.teacher_id))
        assert r.status_code == 403
    r = await _put_goal(db_app, w.a.teacher_id, "physics", 20)
    assert r.status_code == 403
    r = await db_app.client.patch(
        f"/api/v1/classes/{w.a.class_ids[1]}",
        json={"daily_goal": 17},
        headers=db_app.auth(w.a.teacher_id),
    )
    assert r.status_code == 422


async def test_goal_snapshot_raised_not_lowered_mid_day(db_app: DbApp) -> None:
    w = await world(db_app)
    s, t, physics = w.physics_student, w.a.teacher_id, w.a.class_ids[1]
    out = await _patch_class(db_app, t, physics)
    assert (out["daily_goal"], out["leaderboard_enabled"]) == (15, False)
    await _open_lesson(db_app, s, DIST)
    await answer_kp(db_app, s, DIST, "kp1", "CC")
    assert (await _days(db_app, s))[Subject.physics].goal == 15

    assert (await _patch_class(db_app, t, physics, daily_goal=25))["daily_goal"] == 25
    assert (await _days(db_app, s))[Subject.physics].goal == 25  # raised today
    assert (await _patch_class(db_app, t, physics, daily_goal=10))["daily_goal"] == 10
    assert (await _days(db_app, s))[Subject.physics].goal == 25  # never lowered mid-day

    r = await _put_goal(db_app, s, "physics", 30)
    assert r.status_code == 200
    assert (await _days(db_app, s))[Subject.physics].goal == 30
    today = r.json()["today"]
    assert today[0]["goal"] == 30


async def test_meeting_the_goal_is_announced_once_and_lights_the_streak(db_app: DbApp) -> None:
    w = await world(db_app)
    s = w.physics_student
    await _patch_class(db_app, w.a.teacher_id, w.a.class_ids[1], daily_goal=5)
    await _open_lesson(db_app, s, DIST)
    awards = [
        (await answer_kp(db_app, s, DIST, kp, "CC"))[-1]["xp"] for kp in ("kp1", "kp2", "kp3")
    ]
    awards.append((await pass_practice(db_app, s, DIST))["xp"])  # 4 min x 1.2: >= 5 on its own
    total = sum(a["amount"] for a in awards)
    summary = await get(db_app, s, "/api/v1/me/xp")
    assert [a["goal_met_today"] for a in awards].count(True) == 1
    assert summary["streak"] == {"days": 1, "today_met": True}
    assert summary["today"][0]["met"] is True
    assert summary["week_xp"] == summary["total_xp"] == total


# --- leaderboard ----------------------------------------------------------------------------------


async def _seed_event(
    db: DbApp, org_id: uuid.UUID, user: uuid.UUID, subject: Subject, amount: int, day: date
) -> None:
    async with db.sessions() as session:
        concept_id = await session.scalar(select(Concept.id).limit(1))
        session.add(
            XpEvent(
                org_id=org_id,
                student_id=user,
                reason=XpReason.kp,
                concept_id=concept_id,
                subject=subject,
                amount=amount,
                grade=XpGrade.passed if amount > 0 else XpGrade.rushed,
                base_minutes=Decimal(abs(amount)),
                answered=2,
                rushed_count=0,
                hints=0,
                day=day,
            )
        )
        await session.commit()


async def test_leaderboard_visibility_ranking_and_hidden_students(db_app: DbApp) -> None:
    w = await world(db_app)
    t, maths = w.a.teacher_id, w.a.class_ids[0]
    s0, s1, s2 = w.a.student_ids[:3]
    week = ist_week_start(datetime.now(UTC))
    path = f"/api/v1/classes/{maths}/leaderboard"

    r = await db_app.client.get(path, headers=db_app.auth(s0))
    assert r.status_code == 404  # off by default
    staff = await get(db_app, t, path)
    assert staff["enabled"] is False and len(staff["rows"]) == 3
    assert all("student_id" in row for row in staff["rows"])

    await _seed_event(db_app, w.a.org_id, s0, Subject.maths, 6, week)
    await _seed_event(db_app, w.a.org_id, s1, Subject.maths, 6, week)
    await _seed_event(db_app, w.a.org_id, s2, Subject.physics, 40, week)  # another subject
    await _seed_event(db_app, w.a.org_id, s2, Subject.maths, 50, week - timedelta(days=1))
    await _seed_event(db_app, w.a.org_id, s2, Subject.maths, -2, week)
    await _patch_class(db_app, t, maths, leaderboard_enabled=True)

    board = await get(db_app, s0, path)
    assert board["enabled"] is True and board["week_start"] == week.isoformat()
    assert [(r["rank"], r["week_xp"], r["is_me"]) for r in board["rows"]] == [
        (1, 6, True),
        (1, 6, False),
        (3, 0, False),  # floored at 0; last week's XP doesn't count
    ]
    assert all(set(r) == {"rank", "display_name", "week_xp", "is_me"} for r in board["rows"])
    summary = await get(db_app, s0, "/api/v1/me/xp")
    assert [b["class_id"] for b in summary["leaderboards"]] == [str(maths)]

    async with db_app.sessions() as session:
        await session.execute(
            delete(Enrollment).where(Enrollment.class_id == maths, Enrollment.student_id == s1)
        )
        await session.execute(
            update(AppUser).where(AppUser.id == s2).values(status=UserStatus.deactivated)
        )
        await session.commit()
    board = await get(db_app, s0, path)
    assert [r["is_me"] for r in board["rows"]] == [True]
    r = await db_app.client.get(path, headers=db_app.auth(s1))
    assert r.status_code == 404  # no longer enrolled

    other = f"/api/v1/classes/{w.b.class_ids[0]}/leaderboard"
    for user in (t, s0):
        assert (await db_app.client.get(other, headers=db_app.auth(user))).status_code == 404

    await _patch_class(db_app, t, maths, archived=True)
    assert (await db_app.client.get(path, headers=db_app.auth(s0))).status_code == 404
    await _patch_class(db_app, t, maths, archived=False, leaderboard_enabled=False)
    assert (await db_app.client.get(path, headers=db_app.auth(s0))).status_code == 404
    assert (await get(db_app, t, path))["enabled"] is False


async def test_roster_columns_and_streak(db_app: DbApp) -> None:
    w = await world(db_app)
    t, maths = w.a.teacher_id, w.a.class_ids[0]
    s0 = w.a.student_ids[0]
    now = datetime.now(UTC)
    today = ist_date(now)
    await _seed_event(db_app, w.a.org_id, s0, Subject.maths, 9, ist_week_start(now))
    async with db_app.sessions() as session:
        for back in (1, 2, 4):  # yesterday and the day before met; a gap before that
            session.add(
                XpDay(
                    org_id=w.a.org_id,
                    student_id=s0,
                    day=today - timedelta(days=back),
                    subject=Subject.maths,
                    xp=20,
                    goal=15,
                    met_at=now - timedelta(days=back),
                )
            )
        await session.commit()
    rows = {r["id"]: r for r in await get(db_app, t, f"/api/v1/classes/{maths}/students")}
    assert (rows[str(s0)]["week_xp"], rows[str(s0)]["streak_days"]) == (9, 2)
    other = rows[str(w.a.student_ids[1])]
    assert (other["week_xp"], other["streak_days"]) == (0, 0)
    summary = await get(db_app, s0, "/api/v1/me/xp")
    assert summary["streak"] == {"days": 2, "today_met": False}  # an unfinished today
