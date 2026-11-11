"""Erasure (spec 014): request, cancel, completion by the job, and an erased student appearing
nowhere per-student while the learning rows are kept."""

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.ai import teacher_facts as tf
from app.api.deps import CurrentUser, OrgScope
from app.models import (
    AppUser,
    AssignmentStudent,
    Attempt,
    AuditAction,
    AuditEvent,
    Enrollment,
    Role,
    TutorMessage,
    UserStatus,
)
from app.services import class_view, erasure, teacher_ai
from tests.conftest import DbApp
from tests.db_seed import School, grant_consent, seed_school, student
from tests.learn_helpers import world
from tests.test_tutor_api_db import answer, call, kp1_question, tutor_url

pytestmark = pytest.mark.db


async def erase(db: DbApp, admin: uuid.UUID, sid: uuid.UUID, username: str) -> tuple[int, Any]:
    r = await db.client.post(
        f"/api/v1/students/{sid}/erasure",
        json={"confirm_username": username},
        headers=db.auth(admin),
    )
    return r.status_code, r.json()


async def user(db: DbApp, uid: uuid.UUID) -> AppUser:
    async with db.sessions() as session:
        u = await session.get(AppUser, uid)
        assert u is not None
        return u


async def actions(db: DbApp) -> list[tuple[AuditAction, uuid.UUID | None]]:
    async with db.sessions() as session:
        rows = (
            await session.execute(
                select(AuditEvent.action, AuditEvent.actor_id).order_by(
                    AuditEvent.created_at, AuditEvent.id
                )
            )
        ).all()
    return [(a, b) for a, b in rows]


async def run_due(db: DbApp, now: datetime) -> erasure.DueResult:
    async with db.sessions() as session:
        return await erasure.complete_due(session, db.admin, now)


async def school(db: DbApp) -> School:
    async with db.sessions() as session:
        return await seed_school(session, "AAA")


async def test_request_checks_username_bans_first_and_schedules(db_app: DbApp) -> None:
    a = await school(db_app)
    s = a.student_ids[0]
    code, body = await erase(db_app, a.admin_id, s, "wrong")
    assert code == 422 and body["code"] == "confirm_mismatch"
    code, _ = await erase(db_app, a.teacher_id, s, "aaa00")
    assert code == 403

    db_app.admin.fail_on = "set_banned"
    code, body = await erase(db_app, a.admin_id, s, "aaa00")
    assert code == 502
    assert (await user(db_app, s)).erase_requested_at is None
    assert await actions(db_app) == []
    db_app.admin.fail_on = None

    before = datetime.now(UTC)
    code, body = await erase(db_app, a.admin_id, s, " AAA00 ")
    assert code == 200, body
    assert body["status"] == "deactivated" and body["erase_due_at"]
    u = await user(db_app, s)
    assert u.status == UserStatus.deactivated and u.erase_requested_by == a.admin_id
    assert u.erase_due_at and u.erase_requested_at
    assert u.erase_due_at - u.erase_requested_at == timedelta(days=7)
    assert u.erase_requested_at >= before - timedelta(seconds=5)
    assert db_app.admin.users[s]["banned"] is True
    assert await actions(db_app) == [(AuditAction.erase_requested, a.admin_id)]
    async with db_app.sessions() as session:
        meta = await session.scalar(select(AuditEvent.meta))
    assert meta == {"due_at": u.erase_due_at.isoformat(), "was_active": True}

    # Pending: can't sign in, can't be reactivated, can't be requested twice, still exported.
    r = await db_app.client.get("/api/v1/me", headers=db_app.auth(s))
    assert r.status_code == 401
    r = await db_app.client.patch(
        f"/api/v1/students/{s}", json={"status": "active"}, headers=db_app.auth(a.admin_id)
    )
    assert r.status_code == 409 and r.json()["code"] == "erasure_pending"
    code, body = await erase(db_app, a.admin_id, s, "aaa00")
    assert code == 409 and body["code"] == "erasure_pending"
    r = await db_app.client.get(f"/api/v1/students/{s}/export", headers=db_app.auth(a.admin_id))
    assert r.status_code == 200
    r = await db_app.client.get("/api/v1/students", headers=db_app.auth(a.teacher_id))
    row = next(x for x in r.json() if x["id"] == str(s))
    assert row["erase_due_at"] and row["status"] == "deactivated"


async def test_cancel_keeps_the_student_deactivated(db_app: DbApp) -> None:
    a = await school(db_app)
    s = a.student_ids[0]
    h = db_app.auth(a.admin_id)
    r = await db_app.client.delete(f"/api/v1/students/{s}/erasure", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "no_erasure_pending"
    await erase(db_app, a.admin_id, s, "aaa00")
    r = await db_app.client.delete(
        f"/api/v1/students/{s}/erasure", headers=db_app.auth(a.teacher_id)
    )
    assert r.status_code == 403
    r = await db_app.client.delete(f"/api/v1/students/{s}/erasure", headers=h)
    assert r.status_code == 200 and r.json()["erase_due_at"] is None
    assert r.json()["status"] == "deactivated"
    assert [x for x, _ in await actions(db_app)] == [
        AuditAction.erase_requested,
        AuditAction.erase_cancelled,
    ]
    assert (await run_due(db_app, datetime.now(UTC) + timedelta(days=8))).done == []
    r = await db_app.client.patch(f"/api/v1/students/{s}", json={"status": "active"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "active"


async def test_completion_anonymises_and_hides_the_student(db_app: DbApp) -> None:
    w = await world(db_app)
    a = w.a
    async with db_app.sessions() as session:
        await grant_consent(session, a)
    s = a.student_ids[3]  # 9B physics
    q = await kp1_question(db_app, s)
    code, _ = await call(db_app, s, "POST", tutor_url(q, "/messages"), text="help me")
    assert code == 200
    await answer(db_app, s, q, correct=True)
    r = await db_app.client.post(
        f"/api/v1/classes/{a.class_ids[1]}/assignments",
        json={
            "concepts": ["physics/speed-and-velocity"],
            "due_date": str(datetime.now(UTC).date() + timedelta(days=3)),
            "student_ids": [str(s), str(a.student_ids[4])],
        },
        headers=db_app.auth(a.teacher_id),
    )
    assert r.status_code in (200, 201), r.text
    async with db_app.sessions() as session:
        attempts_before = await session.scalar(
            select(func.count()).select_from(Attempt).where(Attempt.student_id == s)
        )
    assert attempts_before

    code, _ = await erase(db_app, a.admin_id, s, "aaa10")
    assert code == 200
    assert (await run_due(db_app, datetime.now(UTC) + timedelta(days=6))).done == []
    result = await run_due(db_app, datetime.now(UTC) + timedelta(days=7, seconds=5))
    assert result.done == [s] and result.failed == []
    assert s in db_app.admin.deleted

    u = await user(db_app, s)
    assert u.status == UserStatus.erased and u.erased_at is not None
    assert u.display_name == "Erased student"
    assert u.username and re.fullmatch(r"erased-[0-9a-f]{12}", u.username)
    assert u.tutor_consent_at is None and u.erase_due_at is None
    async with db_app.sessions() as session:
        for model in (Enrollment, AssignmentStudent):
            n = await session.scalar(
                select(func.count()).select_from(model).where(model.student_id == s)
            )
            assert n == 0, model
        assert (
            await session.scalar(
                select(func.count()).select_from(Attempt).where(Attempt.student_id == s)
            )
            == attempts_before
        )
        texts = (
            await session.scalars(select(TutorMessage.text).where(TutorMessage.student_id == s))
        ).all()
        assert texts and set(texts) == {None}
        scope = OrgScope(session, CurrentUser(a.teacher_id, a.org_id, Role.teacher, False, False))
        ctx = await class_view.load(scope, a.class_ids[1])
        assert s not in {x.id for x in ctx.students}
        facts = tf.class_facts(await teacher_ai.class_input(scope, ctx, "30d"))
        assert str(s) not in {str(v) for v in facts.pseudonyms.values()}
        assert a.student_ids[4] in ctx.student_ids
    assert (AuditAction.erase_completed, None) in await actions(db_app)

    # Nowhere per-student.
    t = db_app.auth(a.teacher_id)
    h = db_app.auth(a.admin_id)
    base = f"/api/v1/classes/{a.class_ids[1]}"
    r = await db_app.client.get("/api/v1/students", headers=t)
    assert str(s) not in {x["id"] for x in r.json()}
    r = await db_app.client.get(f"{base}/students", headers=t)
    assert str(s) not in {x["id"] for x in r.json()}
    r = await db_app.client.get(f"{base}/heatmap", headers=t)
    assert str(s) not in {x["student_id"] for x in r.json()["students"]}
    r = await db_app.client.get(f"{base}/overview", headers=t)
    assert r.json()["students_in_scope"] == 2
    await db_app.client.patch(base, json={"leaderboard_enabled": True}, headers=t)
    r = await db_app.client.get(f"{base}/leaderboard", headers=db_app.auth(a.student_ids[4]))
    assert r.status_code == 200 and str(s) not in r.text
    for method, path, body in (
        ("GET", f"{base}/students/{s}", None),
        ("GET", f"/api/v1/students/{s}/export", None),
        ("POST", f"/api/v1/students/{s}/erasure", {"confirm_username": u.username}),
        ("DELETE", f"/api/v1/students/{s}/erasure", None),
        ("POST", "/api/v1/students/consent", {"student_ids": [str(s)], "action": "record"}),
        ("PATCH", f"/api/v1/students/{s}", {"status": "active"}),
        ("POST", f"/api/v1/classes/{a.class_ids[1]}/enrollments", {"student_ids": [str(s)]}),
    ):
        r = await db_app.client.request(method, path, json=body, headers=h)
        assert r.status_code == 404, (method, path, r.status_code)
    r = await db_app.client.get("/api/v1/me", headers=db_app.auth(s))
    assert r.status_code == 401
    r = await db_app.client.get(f"{base}/assignments", headers=t)
    assert r.status_code == 200

    # The old username is free again (no link to the anonymous row).
    async with db_app.sessions() as session:
        session.add(student(a.org_id, "aaa10"))
        await session.commit()


async def test_auth_404_counts_as_done_and_failures_retry(db_app: DbApp) -> None:
    a = await school(db_app)
    s0, s1 = a.student_ids[:2]
    await erase(db_app, a.admin_id, s0, "aaa00")
    await erase(db_app, a.admin_id, s1, "aaa01")
    later = datetime.now(UTC) + timedelta(days=8)

    db_app.admin.fail_on = "delete_user"
    db_app.admin.fail_status = 500
    result = await run_due(db_app, later)
    assert result.done == [] and sorted(result.failed) == sorted([s0, s1])
    assert (await user(db_app, s0)).status == UserStatus.deactivated
    assert await actions(db_app) == [(AuditAction.erase_requested, a.admin_id)] * 2

    db_app.admin.fail_status = 404  # deleted by hand in the dashboard
    result = await run_due(db_app, later)
    assert sorted(result.done) == sorted([s0, s1]) and result.failed == []
    assert (await user(db_app, s1)).status == UserStatus.erased

    assert (await run_due(db_app, later)).done == []  # idempotent


async def test_two_runs_at_once_erase_each_student_once(db_app: DbApp) -> None:
    a = await school(db_app)
    for i, sid in enumerate(a.student_ids[:3]):
        await erase(db_app, a.admin_id, sid, f"aaa0{i}")
    later = datetime.now(UTC) + timedelta(days=8)
    r1, r2 = await asyncio.gather(run_due(db_app, later), run_due(db_app, later))
    assert sorted(r1.done + r2.done) == sorted(a.student_ids[:3])
    assert r1.failed == r2.failed == []
    completed = [x for x, _ in await actions(db_app) if x == AuditAction.erase_completed]
    assert len(completed) == 3
