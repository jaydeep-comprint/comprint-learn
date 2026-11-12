"""The audit log (spec 014): events written with the change they record, pagination, filters,
admin-only access and no personal data in `meta`."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.api.deps import CurrentUser, OrgScope
from app.models import AppUser, AuditAction, AuditEvent, Role, UserStatus
from app.services import audit, tenancy
from tests.conftest import DbApp
from tests.db_seed import School, seed_school

pytestmark = pytest.mark.db


async def school(db: DbApp, code: str = "AAA") -> School:
    async with db.sessions() as session:
        return await seed_school(session, code)


async def get_audit(db: DbApp, actor: uuid.UUID, **params: Any) -> tuple[int, Any]:
    r = await db.client.get("/api/v1/audit", params=params, headers=db.auth(actor))
    return r.status_code, r.json()


async def all_events(db: DbApp) -> list[AuditEvent]:
    async with db.sessions() as session:
        return list((await session.scalars(select(AuditEvent))).all())


async def test_account_actions_write_events(db_app: DbApp) -> None:
    a = await school(db_app)
    s = a.student_ids[0]
    h = db_app.auth(a.admin_id)
    r = await db_app.client.post(f"/api/v1/students/{s}/reset-password", headers=h)
    assert r.status_code == 200
    r = await db_app.client.patch(
        f"/api/v1/students/{s}", json={"status": "deactivated"}, headers=h
    )
    assert r.status_code == 200
    r = await db_app.client.patch(f"/api/v1/students/{s}", json={"status": "active"}, headers=h)
    assert r.status_code == 200
    r = await db_app.client.patch(
        f"/api/v1/teachers/{a.teacher_id}", json={"status": "deactivated"}, headers=h
    )
    assert r.status_code == 200
    # A rename alone writes nothing.
    r = await db_app.client.patch(f"/api/v1/students/{s}", json={"display_name": "Asha"}, headers=h)
    assert r.status_code == 200

    code, page = await get_audit(db_app, a.admin_id)
    assert code == 200
    got = [(e["action"], e["target"]["id"], e["meta"]) for e in reversed(page["items"])]
    assert got == [
        ("password_reset", str(s), {}),
        ("user_deactivated", str(s), {"role": "student"}),
        ("user_reactivated", str(s), {"role": "student"}),
        ("user_deactivated", str(a.teacher_id), {"role": "teacher"}),
    ]
    first = page["items"][-1]
    assert first["actor"] == {"id": str(a.admin_id), "display_name": "admin"}
    assert first["target"]["display_name"] == "Asha"
    assert page["next_before"] is None


async def test_a_failed_change_leaves_no_event(db_app: DbApp) -> None:
    a = await school(db_app)
    s = a.student_ids[0]
    db_app.admin.fail_on = "set_banned"
    r = await db_app.client.patch(
        f"/api/v1/students/{s}", json={"status": "deactivated"}, headers=db_app.auth(a.admin_id)
    )
    assert r.status_code == 502
    db_app.admin.fail_on = None

    # The event is part of the change's transaction: a rollback drops both.
    async with db_app.sessions() as session:
        scope = OrgScope(session, CurrentUser(a.admin_id, a.org_id, Role.teacher, True, False))
        user = await tenancy.get_student(scope, s, for_update=True)
        await tenancy._set_status(scope, db_app.admin, user, UserStatus.deactivated)
        await session.rollback()
    assert await all_events(db_app) == []
    async with db_app.sessions() as session:
        u = await session.get(AppUser, s)
        assert u is not None and u.status == UserStatus.active


async def test_system_scope_must_pass_a_null_actor(db_app: DbApp) -> None:
    a = await school(db_app)
    async with db_app.sessions() as session:
        scope = OrgScope.system(session, a.org_id)
        with pytest.raises(ValueError):
            audit.record(scope, AuditAction.erase_completed, a.student_ids[0])
        audit.record(scope, AuditAction.erase_completed, a.student_ids[0], actor_id=None)
        await session.commit()
    code, page = await get_audit(db_app, a.admin_id)
    assert code == 200 and page["items"][0]["actor"] is None


async def test_pagination_filters_and_access(db_app: DbApp) -> None:
    a = await school(db_app)
    b = await school(db_app, "BBB")
    # Six events from one request share a `created_at`: the cursor still splits them exactly.
    r = await db_app.client.post(
        "/api/v1/students/consent",
        json={"student_ids": [str(i) for i in a.student_ids], "action": "record"},
        headers=db_app.auth(a.teacher_id),
    )
    assert r.status_code == 200
    r = await db_app.client.post(
        f"/api/v1/students/{a.student_ids[0]}/reset-password", headers=db_app.auth(a.admin_id)
    )
    r = await db_app.client.post(
        f"/api/v1/students/{b.student_ids[0]}/reset-password", headers=db_app.auth(b.admin_id)
    )

    seen: list[str] = []
    before = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2} | ({"before": before} if before else {})
        code, page = await get_audit(db_app, a.admin_id, **params)
        assert code == 200 and len(page["items"]) <= 2
        seen += [e["id"] for e in page["items"]]
        pages += 1
        before = page["next_before"]
        if before is None:
            break
    assert len(seen) == len(set(seen)) == 7 and pages == 4  # other school's event never shown
    code, page = await get_audit(db_app, a.admin_id)
    assert [e["id"] for e in page["items"]] == seen  # newest first, same order as pages
    assert page["items"][0]["action"] == "password_reset"

    code, page = await get_audit(db_app, a.admin_id, action="consent_recorded")
    assert len(page["items"]) == 6
    code, page = await get_audit(db_app, a.admin_id, target_id=str(a.student_ids[0]))
    assert {e["action"] for e in page["items"]} == {"consent_recorded", "password_reset"}
    code, body = await get_audit(db_app, a.admin_id, before="nonsense")
    assert code == 422 and body["code"] == "bad_cursor"

    code, _ = await get_audit(db_app, a.teacher_id)
    assert code == 403
    code, _ = await get_audit(db_app, a.student_ids[0])
    assert code == 403


async def test_no_event_holds_personal_data(db_app: DbApp) -> None:
    a = await school(db_app)
    h = db_app.auth(a.admin_id)
    ids = [str(i) for i in a.student_ids]
    for action in ("record", "withdraw"):
        r = await db_app.client.post(
            "/api/v1/students/consent", json={"student_ids": ids, "action": action}, headers=h
        )
        assert r.status_code == 200
    for sid in a.student_ids:
        await db_app.client.post(f"/api/v1/students/{sid}/reset-password", headers=h)
        await db_app.client.patch(
            f"/api/v1/students/{sid}", json={"status": "deactivated"}, headers=h
        )
    async with db_app.sessions() as session:
        users = (await session.scalars(select(AppUser))).all()
    personal = {v.lower() for u in users for v in (u.display_name, u.username, u.email) if v}
    evs = await all_events(db_app)
    assert len(evs) == 4 * len(a.student_ids)
    for e in evs:
        values = {str(v).lower() for v in e.meta.values()}
        assert not values & personal, e.meta
