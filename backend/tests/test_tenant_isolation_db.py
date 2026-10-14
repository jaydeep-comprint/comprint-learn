"""A teacher (or admin) in school A can never see or change anything in school B."""

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, ClassTeacher, Enrollment, Organization, SchoolClass
from tests.conftest import DbApp
from tests.db_seed import School, seed_school

pytestmark = pytest.mark.db


async def _snapshot(session: AsyncSession, org_id: Any) -> dict[str, list[tuple[Any, ...]]]:
    """Every column of every row school B owns, to prove nothing changed."""
    out: dict[str, list[tuple[Any, ...]]] = {}
    for model in (Organization, AppUser, SchoolClass, ClassTeacher, Enrollment):
        table = model.__table__
        col = table.c.id if model is Organization else table.c.org_id
        rows = (await session.execute(select(table).where(col == org_id))).all()
        out[model.__tablename__] = sorted(tuple(r) for r in rows)
    return out


async def _seed(db: DbApp) -> tuple[School, School]:
    async with db.sessions() as session:
        return await seed_school(session, "AAA"), await seed_school(session, "BBB")


def _cross_school_calls(a: School, b: School) -> list[tuple[str, str, Any, Any]]:
    """(method, path, json body, acting user) for every endpoint, aimed at B's ids."""
    bt, bc, bs = b.teacher_id, b.class_ids[0], b.student_ids[0]
    ac, as_ = a.class_ids[0], a.student_ids[0]
    adm, tch = a.admin_id, a.teacher_id
    return [
        ("POST", f"/api/v1/teachers/{bt}/resend-invite", None, adm),
        ("PATCH", f"/api/v1/teachers/{bt}", {"is_admin": True}, adm),
        ("PATCH", f"/api/v1/teachers/{b.admin_id}", {"status": "deactivated"}, adm),
        ("PATCH", f"/api/v1/students/{bs}", {"display_name": "Hacked"}, tch),
        ("PATCH", f"/api/v1/students/{bs}", {"status": "deactivated"}, adm),
        ("POST", f"/api/v1/students/{bs}/reset-password", None, tch),
        ("GET", f"/api/v1/students?class_id={bc}", None, tch),
        ("GET", f"/api/v1/classes/{bc}", None, tch),
        ("PATCH", f"/api/v1/classes/{bc}", {"name": "Hacked", "archived": True}, tch),
        ("PUT", f"/api/v1/classes/{bc}/teachers/{tch}", None, tch),
        ("PUT", f"/api/v1/classes/{ac}/teachers/{bt}", None, tch),
        ("DELETE", f"/api/v1/classes/{bc}/teachers/{bt}", None, tch),
        ("DELETE", f"/api/v1/classes/{ac}/teachers/{bt}", None, tch),
        ("GET", f"/api/v1/classes/{bc}/students", None, tch),
        ("POST", f"/api/v1/classes/{bc}/students", {"display_names": ["Intruder"]}, tch),
        ("POST", f"/api/v1/classes/{ac}/enrollments", {"student_ids": [str(bs)]}, tch),
        ("POST", f"/api/v1/classes/{ac}/enrollments", {"student_ids": [str(as_), str(bs)]}, tch),
        ("POST", f"/api/v1/classes/{bc}/enrollments", {"student_ids": [str(as_)]}, tch),
        ("DELETE", f"/api/v1/classes/{bc}/enrollments/{bs}", None, tch),
        ("DELETE", f"/api/v1/classes/{ac}/enrollments/{bs}", None, tch),
    ]


async def test_every_endpoint_404s_on_other_school_ids(db_app: DbApp) -> None:
    a, b = await _seed(db_app)
    async with db_app.sessions() as session:
        before_b = await _snapshot(session, b.org_id)
        before_a = await _snapshot(session, a.org_id)

    for method, path, body, actor in _cross_school_calls(a, b):
        resp = await db_app.client.request(method, path, json=body, headers=db_app.auth(actor))
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code} {resp.text}"
        assert resp.json()["code"] == "not_found"

    async with db_app.sessions() as session:
        assert await _snapshot(session, b.org_id) == before_b
        assert await _snapshot(session, a.org_id) == before_a
    assert db_app.admin.calls == []  # no Supabase calls for anyone in B


async def test_list_endpoints_return_only_own_school(db_app: DbApp) -> None:
    a, _b = await _seed(db_app)
    h = db_app.auth(a.teacher_id)

    teachers = (await db_app.client.get("/api/v1/teachers", headers=h)).json()
    assert {t["id"] for t in teachers} == {str(a.admin_id), str(a.teacher_id)}

    students = (await db_app.client.get("/api/v1/students", headers=h)).json()
    assert {s["id"] for s in students} == {str(s) for s in a.student_ids}
    # A search that matches B's usernames ("bbb00") finds nothing.
    assert (await db_app.client.get("/api/v1/students?q=bbb", headers=h)).json() == []

    for query in ("", "?archived=true", "?mine=true"):
        classes = (await db_app.client.get(f"/api/v1/classes{query}", headers=h)).json()
        assert {c["id"] for c in classes} == {str(c) for c in a.class_ids}

    me = (await db_app.client.get("/api/v1/me", headers=h)).json()
    assert me["org"]["code"] == "AAA"


async def test_db_rejects_cross_school_links(db_app: DbApp) -> None:
    a, b = await _seed(db_app)
    async with db_app.sessions() as session:
        with pytest.raises(IntegrityError):
            # Claims school A, but the student belongs to B: the composite FK refuses it.
            await session.execute(
                text("INSERT INTO enrollment (class_id, student_id, org_id) VALUES (:c, :s, :o)"),
                {"c": a.class_ids[0], "s": b.student_ids[0], "o": a.org_id},
            )
        await session.rollback()
        with pytest.raises(IntegrityError):
            await session.execute(
                text("INSERT INTO class_teacher (class_id, user_id, org_id) VALUES (:c, :u, :o)"),
                {"c": b.class_ids[0], "u": a.teacher_id, "o": b.org_id},
            )
