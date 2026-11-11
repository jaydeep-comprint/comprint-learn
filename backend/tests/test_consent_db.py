"""AI-tutor consent (spec 014): record and withdraw in bulk, all-or-nothing errors, withdrawal
nulls only that student's chat text, audit events, and concurrent records."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text

from app.models import AppUser, AuditAction, AuditEvent, TutorMessage, TutorStatus
from app.privacy import NOTICE_VERSION
from tests.conftest import DbApp
from tests.db_seed import School, grant_consent, seed_school
from tests.learn_helpers import world
from tests.test_tutor_api_db import call, kp1_question, tutor_url

pytestmark = pytest.mark.db

PATH = "/api/v1/students/consent"


async def consent(
    db: DbApp, actor: uuid.UUID, ids: list[uuid.UUID], action: str
) -> tuple[int, Any]:
    r = await db.client.post(
        PATH, json={"student_ids": [str(i) for i in ids], "action": action}, headers=db.auth(actor)
    )
    return r.status_code, r.json()


async def events(db: DbApp, action: AuditAction | None = None) -> list[AuditEvent]:
    async with db.sessions() as session:
        stmt = select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)
        if action is not None:
            stmt = stmt.where(AuditEvent.action == action)
        return list((await session.scalars(stmt)).all())


async def user(db: DbApp, uid: uuid.UUID) -> AppUser:
    async with db.sessions() as session:
        u = await session.get(AppUser, uid)
        assert u is not None
        return u


async def school(db: DbApp, code: str = "AAA") -> School:
    async with db.sessions() as session:
        return await seed_school(session, code)


async def test_record_in_bulk_is_idempotent_per_student(db_app: DbApp) -> None:
    a = await school(db_app)
    s0, s1, s2 = a.student_ids[:3]
    async with db_app.sessions() as session:
        await grant_consent(session, a, [s2])
    before = await user(db_app, s2)

    code, out = await consent(db_app, a.teacher_id, [s0, s1, s2, s0], "record")
    assert code == 200, out
    assert {r["id"] for r in out} == {str(s0), str(s1), str(s2)}
    assert all(r["tutor_consent_form"] == NOTICE_VERSION for r in out)
    assert all(r["tutor_consent_at"] for r in out)
    u0 = await user(db_app, s0)
    assert u0.tutor_consent_by == a.teacher_id and u0.tutor_consent_form == NOTICE_VERSION
    assert (await user(db_app, s2)).tutor_consent_at == before.tutor_consent_at  # unchanged
    recorded = await events(db_app, AuditAction.consent_recorded)
    assert sorted(e.target_id for e in recorded) == sorted([s0, s1])  # type: ignore[type-var]
    assert all(e.actor_id == a.teacher_id and e.meta == {"form": NOTICE_VERSION} for e in recorded)

    code, _ = await consent(db_app, a.teacher_id, [s0, s1], "record")
    assert code == 200
    assert len(await events(db_app)) == 2  # repeats write nothing

    # Shown on the class roster and the school Students page.
    r = await db_app.client.get(
        f"/api/v1/classes/{a.class_ids[0]}/students", headers=db_app.auth(a.teacher_id)
    )
    roster = {row["id"]: row for row in r.json()}
    assert roster[str(s0)]["tutor_consent_form"] == NOTICE_VERSION
    r = await db_app.client.get("/api/v1/students", headers=db_app.auth(a.admin_id))
    listed = {row["id"]: row for row in r.json()}
    assert (
        listed[str(s1)]["tutor_consent_at"]
        and listed[str(a.student_ids[4])]["tutor_consent_at"] is None
    )


async def test_errors_are_all_or_nothing(db_app: DbApp) -> None:
    a = await school(db_app)
    b = await school(db_app, "BBB")
    s0, s1 = a.student_ids[:2]
    for bad in (a.teacher_id, b.student_ids[0], uuid.uuid4()):
        code, body = await consent(db_app, a.teacher_id, [s0, bad], "record")
        assert code == 404 and body["code"] == "not_found"
    code, body = await consent(db_app, a.teacher_id, [uuid.uuid4() for _ in range(201)], "record")
    assert code == 422

    async with db_app.sessions() as session:
        await session.execute(
            text(
                "UPDATE app_user SET status = 'deactivated', erase_requested_at = now(), "
                "erase_requested_by = :admin, erase_due_at = now() + interval '7 days' "
                "WHERE id = :s"
            ),
            {"admin": a.admin_id, "s": s1},
        )
        await session.commit()
    code, body = await consent(db_app, a.teacher_id, [s0, s1], "record")
    assert code == 422 and body["code"] == "consent_not_allowed"
    assert body["student_ids"] == [str(s1)]
    assert (await user(db_app, s0)).tutor_consent_at is None
    assert await events(db_app) == []

    # Withdrawal is allowed for a student with a pending erasure (a no-op without consent).
    code, _ = await consent(db_app, a.teacher_id, [s1], "withdraw")
    assert code == 200

    async with db_app.sessions() as session:
        await session.execute(
            text(
                "UPDATE app_user SET status = 'erased', erased_at = now(), erase_requested_at = "
                "NULL, erase_requested_by = NULL, erase_due_at = NULL WHERE id = :s"
            ),
            {"s": s1},
        )
        await session.commit()
    for action in ("record", "withdraw"):
        code, body = await consent(db_app, a.teacher_id, [s0, s1], action)
        assert code == 404


async def test_students_cannot_record_consent(db_app: DbApp) -> None:
    a = await school(db_app)
    code, _ = await consent(db_app, a.student_ids[0], [a.student_ids[0]], "record")
    assert code == 403


async def test_withdraw_nulls_only_that_students_text_and_keeps_counts(db_app: DbApp) -> None:
    w = await world(db_app)
    async with db_app.sessions() as session:
        await grant_consent(session, w.a)
    s, other = w.a.student_ids[3], w.a.student_ids[4]
    questions = {}
    for student in (s, other):
        q = questions[student] = await kp1_question(db_app, student)
        code, _ = await call(db_app, student, "POST", tutor_url(q, "/hint"))
        assert code == 200
        code, _ = await call(db_app, student, "POST", tutor_url(q, "/messages"), text="why?")
        assert code == 200

    code, out = await consent(db_app, w.a.teacher_id, [s], "withdraw")
    assert code == 200 and out[0]["tutor_consent_at"] is None
    async with db_app.sessions() as session:
        msgs = list((await session.scalars(select(TutorMessage))).all())
    mine = [m for m in msgs if m.student_id == s]
    theirs = [m for m in msgs if m.student_id == other]
    assert len(mine) == 4 and all(m.text is None and m.purged_at is not None for m in mine)
    assert all(m.status == TutorStatus.ok for m in mine)  # status and counts stay
    assert any(m.input_tokens for m in mine)
    assert all(m.purged_at is None for m in theirs) and any(m.text for m in theirs)
    withdrawn = await events(db_app, AuditAction.consent_withdrawn)
    assert [(e.target_id, e.meta) for e in withdrawn] == [
        (s, {"form": NOTICE_VERSION, "messages_purged": 4})
    ]

    # The student sees the lock; recording again unlocks; the text does not come back.
    code, thread = await call(db_app, s, "GET", tutor_url(questions[s]))
    assert code == 200 and thread["consent"] is False
    assert all(m["text"] is None for m in thread["messages"])
    code, _ = await consent(db_app, w.a.teacher_id, [s], "withdraw")
    assert code == 200 and len(await events(db_app, AuditAction.consent_withdrawn)) == 1
    code, _ = await consent(db_app, w.a.teacher_id, [s], "record")
    assert code == 200
    async with db_app.sessions() as session:
        texts = (
            await session.scalars(select(TutorMessage.text).where(TutorMessage.student_id == s))
        ).all()
    assert set(texts) == {None}


async def test_concurrent_records_write_one_event(db_app: DbApp) -> None:
    a = await school(db_app)
    s = a.student_ids[0]
    results = await asyncio.gather(
        consent(db_app, a.teacher_id, [s], "record"),
        consent(db_app, a.admin_id, [s], "record"),
    )
    assert [code for code, _ in results] == [200, 200]
    assert len(await events(db_app, AuditAction.consent_recorded)) == 1
    stamps = {body[0]["tutor_consent_at"] for _, body in results}
    assert len(stamps) == 1
