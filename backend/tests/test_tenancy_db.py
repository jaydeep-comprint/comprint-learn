"""Tenancy business rules against a real database (Supabase admin API faked)."""

import re
import uuid

import pytest
from sqlalchemy import func, select

from app.cli import CliError, create_org
from app.models import AppUser, Enrollment, Organization, Role, UserStatus
from app.services.tenancy import BULK_CREATE_FAILED, LAST_ADMIN, ONLY_ACTIVE_STUDENTS
from tests.conftest import DbApp
from tests.db_seed import School, seed_school, staff, student

pytestmark = pytest.mark.db


async def _school(db: DbApp, code: str = "TST") -> School:
    async with db.sessions() as session:
        return await seed_school(session, code)


async def _user(db: DbApp, user_id: uuid.UUID | str) -> AppUser:
    async with db.sessions() as session:
        user = await session.get(AppUser, uuid.UUID(str(user_id)))
        assert user is not None
        return user


# --- bulk create ------------------------------------------------------------------------------


async def test_bulk_create_students(db_app: DbApp) -> None:
    s = await _school(db_app)
    names = ["Aarav S.", "Aarav S.", "आरव शर्मा", "  Priya K ", "", "Zoë"]
    resp = await db_app.client.post(
        f"/api/v1/classes/{s.class_ids[0]}/students",
        json={"display_names": names},
        headers=db_app.auth(s.teacher_id),
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert [c["display_name"] for c in created] == [
        "Aarav S.",
        "Aarav S.",
        "आरव शर्मा",
        "Priya K",
        "Zoë",
    ]
    usernames = [c["username"] for c in created]
    assert len(set(usernames)) == 5
    assert re.fullmatch(r"aarav\d{2,4}", usernames[0])
    assert re.fullmatch(r"student\d{2,4}", usernames[2])
    for c in created:
        assert re.fullmatch(r"[a-z]+-[a-z]+-\d{2}", c["temp_password"])
        auth = db_app.admin.users[uuid.UUID(c["id"])]
        assert auth["email"] == f"{c['username']}@tst.students.invalid"
        assert auth["password"] == c["temp_password"]
        user = await _user(db_app, c["id"])
        assert user.role == Role.student and user.must_change_password and user.email is None

    roster = await db_app.client.get(
        f"/api/v1/classes/{s.class_ids[0]}/students", headers=db_app.auth(s.teacher_id)
    )
    assert len(roster.json()) == 3 + 5
    assert "temp_password" not in roster.text


async def test_bulk_create_is_all_or_nothing(db_app: DbApp) -> None:
    s = await _school(db_app)
    db_app.admin.fail_on, db_app.admin.fail_after = "create_user", 2
    async with db_app.sessions() as session:
        before = await session.scalar(select(func.count()).select_from(AppUser))
    resp = await db_app.client.post(
        f"/api/v1/classes/{s.class_ids[0]}/students",
        json={"display_names": ["A", "B", "C", "D"]},
        headers=db_app.auth(s.teacher_id),
    )
    assert resp.status_code == 502
    assert resp.json()["message"] == BULK_CREATE_FAILED
    assert len(db_app.admin.deleted) == 2  # the two that succeeded were deleted again
    assert db_app.admin.users == {}
    async with db_app.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AppUser)) == before


async def test_bulk_create_limits(db_app: DbApp) -> None:
    s = await _school(db_app)
    url, h = f"/api/v1/classes/{s.class_ids[0]}/students", db_app.auth(s.teacher_id)
    too_many = await db_app.client.post(url, json={"display_names": ["x"] * 61}, headers=h)
    assert too_many.status_code == 422
    blank = await db_app.client.post(url, json={"display_names": ["", "  "]}, headers=h)
    assert blank.status_code == 422
    too_long = await db_app.client.post(url, json={"display_names": ["x" * 41]}, headers=h)
    assert too_long.status_code == 422
    assert db_app.admin.calls == []


async def test_usernames_avoid_existing_ones_case_insensitively(db_app: DbApp) -> None:
    s = await _school(db_app)
    async with db_app.sessions() as session:
        # Occupy every 2-digit "max" username so the generator must go to 3 digits.
        session.add_all(student(s.org_id, f"MAX{i:02d}") for i in range(100))
        await session.commit()
    resp = await db_app.client.post(
        f"/api/v1/classes/{s.class_ids[0]}/students",
        json={"display_names": ["Max"]},
        headers=db_app.auth(s.teacher_id),
    )
    assert resp.status_code == 201, resp.text
    assert re.fullmatch(r"max\d{3,4}", resp.json()[0]["username"])


# --- enrolment --------------------------------------------------------------------------------


async def test_add_existing_and_unenrol_are_idempotent(db_app: DbApp) -> None:
    s = await _school(db_app)
    h = db_app.auth(s.teacher_id)
    other_class, from_first = s.class_ids[1], s.student_ids[:2]
    body = {"student_ids": [str(i) for i in from_first]}
    for _ in range(2):
        resp = await db_app.client.post(
            f"/api/v1/classes/{other_class}/enrollments", json=body, headers=h
        )
        assert resp.status_code == 204, resp.text
    roster = (await db_app.client.get(f"/api/v1/classes/{other_class}/students", headers=h)).json()
    assert len(roster) == 5

    for _ in range(2):
        resp = await db_app.client.delete(
            f"/api/v1/classes/{other_class}/enrollments/{from_first[0]}", headers=h
        )
        assert resp.status_code == 204
    assert (await _user(db_app, from_first[0])).status == UserStatus.active  # account kept
    roster = (await db_app.client.get(f"/api/v1/classes/{other_class}/students", headers=h)).json()
    assert len(roster) == 4


async def test_only_active_students_can_be_enrolled(db_app: DbApp) -> None:
    s = await _school(db_app)
    async with db_app.sessions() as session:
        gone = student(s.org_id, "gone11", status=UserStatus.deactivated)
        session.add(gone)
        await session.commit()
    for bad in (s.admin_id, gone.id):
        resp = await db_app.client.post(
            f"/api/v1/classes/{s.class_ids[0]}/enrollments",
            json={"student_ids": [str(s.student_ids[3]), str(bad)]},
            headers=db_app.auth(s.teacher_id),
        )
        assert resp.status_code == 422
        assert resp.json()["message"] == ONLY_ACTIVE_STUDENTS
    async with db_app.sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Enrollment)
            .where(Enrollment.class_id == s.class_ids[0])
        )
    assert count == 3  # the valid id in the same request wasn't enrolled either


async def test_archived_class_is_read_only(db_app: DbApp) -> None:
    s = await _school(db_app)
    h, cid = db_app.auth(s.teacher_id), s.class_ids[0]
    resp = await db_app.client.patch(f"/api/v1/classes/{cid}", json={"archived": True}, headers=h)
    assert resp.status_code == 200 and resp.json()["archived"] is True
    enrol = await db_app.client.post(
        f"/api/v1/classes/{cid}/enrollments",
        json={"student_ids": [str(s.student_ids[3])]},
        headers=h,
    )
    assert enrol.status_code == 409
    create = await db_app.client.post(
        f"/api/v1/classes/{cid}/students", json={"display_names": ["New"]}, headers=h
    )
    assert create.status_code == 409
    unenrol = await db_app.client.delete(
        f"/api/v1/classes/{cid}/enrollments/{s.student_ids[0]}", headers=h
    )
    assert unenrol.status_code == 409

    mine = (await db_app.client.get("/api/v1/classes?mine=true", headers=h)).json()
    assert str(cid) not in {c["id"] for c in mine}
    with_archived = await db_app.client.get("/api/v1/classes?mine=true&archived=true", headers=h)
    assert str(cid) in {c["id"] for c in with_archived.json()}


# --- classes ----------------------------------------------------------------------------------


async def test_class_create_and_name_rules(db_app: DbApp) -> None:
    s = await _school(db_app)
    h = db_app.auth(s.admin_id)
    body = {"name": " 10C Python ", "subject": "python", "grade": 10}
    resp = await db_app.client.post("/api/v1/classes", json=body, headers=h)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "10C Python"
    assert [t["id"] for t in created["teachers"]] == [str(s.admin_id)]  # creator is first teacher

    dup = await db_app.client.post(
        "/api/v1/classes", json={**body, "name": "10c python"}, headers=h
    )
    assert dup.status_code == 409 and dup.json()["code"] == "class_name_taken"

    await db_app.client.patch(
        f"/api/v1/classes/{created['id']}", json={"archived": True}, headers=h
    )
    again = await db_app.client.post("/api/v1/classes", json=body, headers=h)
    assert again.status_code == 201  # archived names can be reused

    bad_grade = await db_app.client.post(
        "/api/v1/classes", json={**body, "name": "x", "grade": 11}, headers=h
    )
    assert bad_grade.status_code == 422


async def test_co_teachers(db_app: DbApp) -> None:
    s = await _school(db_app)
    h, cid = db_app.auth(s.teacher_id), s.class_ids[0]
    for _ in range(2):
        resp = await db_app.client.put(f"/api/v1/classes/{cid}/teachers/{s.admin_id}", headers=h)
        assert resp.status_code == 204
    teachers = (await db_app.client.get(f"/api/v1/classes/{cid}", headers=h)).json()["teachers"]
    assert {t["id"] for t in teachers} == {str(s.admin_id), str(s.teacher_id)}

    as_student = await db_app.client.put(
        f"/api/v1/classes/{cid}/teachers/{s.student_ids[0]}", headers=h
    )
    assert as_student.status_code == 404

    resp = await db_app.client.delete(f"/api/v1/classes/{cid}/teachers/{s.admin_id}", headers=h)
    assert resp.status_code == 204
    teachers = (await db_app.client.get(f"/api/v1/classes/{cid}", headers=h)).json()["teachers"]
    assert [t["id"] for t in teachers] == [str(s.teacher_id)]


# --- teachers and admins ----------------------------------------------------------------------


async def test_invite_then_first_me_activates(db_app: DbApp) -> None:
    s = await _school(db_app)
    resp = await db_app.client.post(
        "/api/v1/teachers/invite",
        json={"email": "New.Teacher@X.in", "display_name": "Mr New"},
        headers=db_app.auth(s.admin_id),
    )
    assert resp.status_code == 201, resp.text
    invited = resp.json()
    assert invited["status"] == "invited" and invited["email"] == "new.teacher@x.in"
    assert db_app.admin.invites == ["new.teacher@x.in"]

    resend = await db_app.client.post(
        f"/api/v1/teachers/{invited['id']}/resend-invite", headers=db_app.auth(s.admin_id)
    )
    assert resend.status_code == 204

    me = await db_app.client.get("/api/v1/me", headers=db_app.auth(invited["id"]))
    assert me.status_code == 200
    assert (await _user(db_app, invited["id"])).status == UserStatus.active

    resend = await db_app.client.post(
        f"/api/v1/teachers/{invited['id']}/resend-invite", headers=db_app.auth(s.admin_id)
    )
    assert resend.status_code == 409


async def test_invite_email_in_any_school_is_409(db_app: DbApp) -> None:
    s = await _school(db_app)
    other = await _school(db_app, "OTH")
    resp = await db_app.client.post(
        "/api/v1/teachers/invite",
        json={"email": "TEACHER@oth.in", "display_name": "Dup"},
        headers=db_app.auth(s.admin_id),
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == "That email already belongs to a user."
    assert "OTH" not in resp.text and str(other.org_id) not in resp.text
    assert db_app.admin.calls == []


async def test_invite_supabase_down_is_502_and_saves_nothing(db_app: DbApp) -> None:
    s = await _school(db_app)
    db_app.admin.fail_on = "invite"
    resp = await db_app.client.post(
        "/api/v1/teachers/invite",
        json={"email": "n@x.in", "display_name": "N"},
        headers=db_app.auth(s.admin_id),
    )
    assert resp.status_code == 502
    async with db_app.sessions() as session:
        assert await session.scalar(select(AppUser).where(AppUser.email == "n@x.in")) is None


async def test_last_admin_rule(db_app: DbApp) -> None:
    s = await _school(db_app)
    h = db_app.auth(s.admin_id)
    for body in ({"is_admin": False}, {"status": "deactivated"}):
        resp = await db_app.client.patch(f"/api/v1/teachers/{s.admin_id}", json=body, headers=h)
        assert resp.status_code == 409
        assert resp.json()["message"] == LAST_ADMIN

    promote = await db_app.client.patch(
        f"/api/v1/teachers/{s.teacher_id}", json={"is_admin": True}, headers=h
    )
    assert promote.status_code == 200 and promote.json()["is_admin"] is True
    # With a second admin, the first may deactivate themselves (and is then signed out).
    resp = await db_app.client.patch(
        f"/api/v1/teachers/{s.admin_id}", json={"status": "deactivated"}, headers=h
    )
    assert resp.status_code == 200
    assert "set_banned" in db_app.admin.calls
    assert (await db_app.client.get("/api/v1/me", headers=h)).status_code == 401
    # The remaining admin can't remove their own admin role now.
    last = await db_app.client.patch(
        f"/api/v1/teachers/{s.teacher_id}",
        json={"is_admin": False},
        headers=db_app.auth(s.teacher_id),
    )
    assert last.status_code == 409


async def test_teacher_routes_admin_only(db_app: DbApp) -> None:
    s = await _school(db_app)
    resp = await db_app.client.patch(
        f"/api/v1/teachers/{s.admin_id}",
        json={"is_admin": False},
        headers=db_app.auth(s.teacher_id),
    )
    assert resp.status_code == 403
    listing = await db_app.client.get("/api/v1/teachers", headers=db_app.auth(s.teacher_id))
    assert listing.status_code == 200


# --- students ---------------------------------------------------------------------------------


async def test_reset_password_and_forced_change(db_app: DbApp) -> None:
    s = await _school(db_app)
    sid = s.student_ids[0]
    db_app.admin.users[sid] = {"email": "x", "password": "old", "banned": False}
    resp = await db_app.client.post(
        f"/api/v1/students/{sid}/reset-password", headers=db_app.auth(s.teacher_id)
    )
    assert resp.status_code == 200
    slip = resp.json()
    assert slip["username"] == "tst00"
    assert db_app.admin.users[sid]["password"] == slip["temp_password"]

    h = db_app.auth(sid)
    me = (await db_app.client.get("/api/v1/me", headers=h)).json()
    assert me["must_change_password"] is True and me["username"] == "tst00"
    blocked = await db_app.client.get("/api/v1/classes", headers=h)
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"

    short = await db_app.client.post(
        "/api/v1/me/password", json={"new_password": "short"}, headers=h
    )
    assert short.status_code == 422
    ok = await db_app.client.post(
        "/api/v1/me/password", json={"new_password": "my-own-secret"}, headers=h
    )
    assert ok.status_code == 204
    assert db_app.admin.users[sid]["password"] == "my-own-secret"
    assert (await db_app.client.get("/api/v1/me", headers=h)).json()[
        "must_change_password"
    ] is False
    # A student still can't use staff routes.
    assert (await db_app.client.get("/api/v1/classes", headers=h)).status_code == 403


async def test_deactivate_student_admin_only_and_signs_out(db_app: DbApp) -> None:
    s = await _school(db_app)
    sid = s.student_ids[0]
    db_app.admin.users[sid] = {"email": "x", "password": "p", "banned": False}
    body = {"status": "deactivated"}
    as_teacher = await db_app.client.patch(
        f"/api/v1/students/{sid}", json=body, headers=db_app.auth(s.teacher_id)
    )
    assert as_teacher.status_code == 403

    db_app.admin.fail_on = "set_banned"
    down = await db_app.client.patch(
        f"/api/v1/students/{sid}", json=body, headers=db_app.auth(s.admin_id)
    )
    assert down.status_code == 502
    assert (await _user(db_app, sid)).status == UserStatus.active  # DB only after the ban
    db_app.admin.fail_on = None

    ok = await db_app.client.patch(
        f"/api/v1/students/{sid}", json=body, headers=db_app.auth(s.admin_id)
    )
    assert ok.status_code == 200 and ok.json()["status"] == "deactivated"
    assert db_app.admin.users[sid]["banned"] is True
    assert (await db_app.client.get("/api/v1/me", headers=db_app.auth(sid))).status_code == 401

    back = await db_app.client.patch(
        f"/api/v1/students/{sid}", json={"status": "active"}, headers=db_app.auth(s.admin_id)
    )
    assert back.status_code == 200 and db_app.admin.users[sid]["banned"] is False


async def test_student_search_and_class_filter(db_app: DbApp) -> None:
    s = await _school(db_app)
    h = db_app.auth(s.teacher_id)
    by_username = (await db_app.client.get("/api/v1/students?q=TST1", headers=h)).json()
    assert {x["username"] for x in by_username} == {"tst10", "tst11", "tst12"}
    wildcard = (await db_app.client.get("/api/v1/students?q=%25", headers=h)).json()
    assert wildcard == []  # % is matched literally
    in_class = (
        await db_app.client.get(f"/api/v1/students?class_id={s.class_ids[1]}", headers=h)
    ).json()
    assert len(in_class) == 3
    assert all(x["class_ids"] == [str(s.class_ids[1])] for x in in_class)


# --- CLI --------------------------------------------------------------------------------------


async def test_cli_org_create(db_app: DbApp) -> None:
    org = await create_org(
        db_app.admin, name="Test School", code="tst", admin_email="A@x.in", admin_name="Ms Rao"
    )
    assert org.code == "TST"
    async with db_app.sessions() as session:
        admin = await session.scalar(select(AppUser).where(AppUser.org_id == org.id))
    assert admin is not None
    assert admin.is_admin and admin.status == UserStatus.invited and admin.email == "a@x.in"

    with pytest.raises(CliError, match=re.escape("School code TST is already taken.")):
        await create_org(
            db_app.admin, name="Other", code="TST", admin_email="b@x.in", admin_name="B"
        )
    with pytest.raises(CliError, match=re.escape("That email already belongs to a user.")):
        await create_org(
            db_app.admin, name="Other", code="OTH", admin_email="a@X.in", admin_name="B"
        )
    db_app.admin.fail_on = "invite"
    with pytest.raises(CliError):
        await create_org(
            db_app.admin, name="Other", code="OTH", admin_email="c@x.in", admin_name="C"
        )
    async with db_app.sessions() as session:
        codes = (await session.scalars(select(Organization.code))).all()
    assert codes == ["TST"]  # no half-created school


async def test_staff_email_unique_across_schools_at_db_level(db_app: DbApp) -> None:
    s = await _school(db_app)
    other = await _school(db_app, "OTH")
    async with db_app.sessions() as session:
        session.add(staff(other.org_id, f"ADMIN@{s.code.lower()}.in"))
        with pytest.raises(Exception, match="uq_app_user_email"):
            await session.commit()
