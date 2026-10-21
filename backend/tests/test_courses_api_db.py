"""`/courses` and `/courses/{slug}/graph`: global content for any signed-in user; never answers."""

from pathlib import Path

import pytest

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.importer import import_tree
from tests import content_fixtures as fx
from tests.conftest import DbApp
from tests.db_seed import seed_school

pytestmark = pytest.mark.db

FORBIDDEN = {
    "correct",
    "misconception",
    "solution",
    "derived",
    "constraints",
    "explanation",
    "answer",
    "items",
    "public",
    "prompt",
}


def _keys(data: object) -> set[str]:
    if isinstance(data, dict):
        return set(data) | {k for v in data.values() for k in _keys(v)}
    if isinstance(data, list):
        return {k for v in data for k in _keys(v)}
    return set()


async def _setup(db: DbApp) -> tuple[dict[str, str], dict[str, str]]:
    issues, report = await import_tree(DEFAULT_CONTENT_ROOT, db.sessions)
    assert report is not None, issues
    async with db.sessions() as session:
        a = await seed_school(session, "AAA")
        b = await seed_school(session, "BBB")
    return db.auth(a.teacher_id), db.auth(b.student_ids[0])


async def test_any_school_any_role_sees_the_same_courses(db_app: DbApp) -> None:
    teacher_a, student_b = await _setup(db_app)
    r1 = await db_app.client.get("/api/v1/courses", headers=teacher_a)
    r2 = await db_app.client.get("/api/v1/courses", headers=student_b)
    assert r1.status_code == r2.status_code == 200, r1.text
    assert r1.json() == r2.json()
    assert r1.json() == [
        {
            "slug": "maths-9-10",
            "title": r1.json()[0]["title"],
            "subject": "maths",
            "chapter_count": 2,
            "concept_count": 3,
        },
        {
            "slug": "physics-9-10",
            "title": r1.json()[1]["title"],
            "subject": "physics",
            "chapter_count": 1,
            "concept_count": 3,
        },
        {
            "slug": "python-basics",
            "title": r1.json()[2]["title"],
            "subject": "python",
            "chapter_count": 1,
            "concept_count": 3,
        },
    ]


async def test_physics_graph(db_app: DbApp) -> None:
    teacher_a, _ = await _setup(db_app)
    resp = await db_app.client.get("/api/v1/courses/physics-9-10/graph", headers=teacher_a)
    assert resp.status_code == 200, resp.text
    graph = resp.json()
    assert graph["course"]["slug"] == "physics-9-10"
    assert [c["id"] for c in graph["concepts"]] == [
        "physics-9-10/distance-and-displacement",
        "physics-9-10/speed-and-velocity",
        "physics-9-10/acceleration",
    ]
    assert all(c["kp_count"] == 3 and c["chapter"] == "motion" for c in graph["concepts"])
    edges = {(e["from"], e["to"]): e["weight"] for e in graph["edges"]}
    assert edges[("physics-9-10/distance-and-displacement", "physics-9-10/speed-and-velocity")]
    assert edges[("physics-9-10/speed-and-velocity", "physics-9-10/acceleration")]
    assert (
        edges[("maths-9-10/linear-equations-two-variables", "physics-9-10/speed-and-velocity")]
        == 0.2
    )
    assert [e["id"] for e in graph["external"]] == ["maths-9-10/linear-equations-two-variables"]
    assert graph["external"][0]["course"] == "maths-9-10"
    assert not (_keys(graph) & FORBIDDEN)


async def test_no_response_leaks_answers(db_app: DbApp) -> None:
    teacher_a, student_b = await _setup(db_app)
    for slug in ("maths-9-10", "physics-9-10", "python-basics"):
        resp = await db_app.client.get(f"/api/v1/courses/{slug}/graph", headers=student_b)
        assert resp.status_code == 200
        assert not (_keys(resp.json()) & FORBIDDEN)
    resp = await db_app.client.get("/api/v1/courses", headers=teacher_a)
    assert not (_keys(resp.json()) & FORBIDDEN)


async def test_unknown_slug_404_and_unauthenticated_401(db_app: DbApp) -> None:
    teacher_a, _ = await _setup(db_app)
    resp = await db_app.client.get("/api/v1/courses/chemistry/graph", headers=teacher_a)
    assert resp.status_code == 404 and resp.json()["code"] == "not_found"
    for path in ("/api/v1/courses", "/api/v1/courses/physics-9-10/graph"):
        assert (await db_app.client.get(path)).status_code == 401


async def test_retired_course_is_404_and_unlisted(db_app: DbApp, tmp_path: Path) -> None:
    physics = fx.course("physics", "physics", concepts=[fx.concept("motion")])
    for name, tree in (("v1", fx.tree(fx.course(), physics)), ("v2", fx.tree(fx.course()))):
        _, report = await import_tree(fx.write(tmp_path / name, tree), db_app.sessions)
        assert report is not None
    async with db_app.sessions() as session:
        school = await seed_school(session, "CCC")
    headers = db_app.auth(school.teacher_id)
    resp = await db_app.client.get("/api/v1/courses/physics/graph", headers=headers)
    assert resp.status_code == 404
    listed = await db_app.client.get("/api/v1/courses", headers=headers)
    assert [c["slug"] for c in listed.json()] == ["maths"]
