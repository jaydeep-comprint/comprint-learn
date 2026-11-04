"""Shared helpers for the Learn / KP DB tests: the imported sample content, two schools, and
drivers that answer questions correctly (or not) by reading the answer key server side."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.importer import import_tree
from app.content.params import sample_answer
from app.grading import grade
from app.grading.expression import answer_text
from app.models import Item, PracticeSession
from tests.conftest import DbApp
from tests.db_seed import School, seed_school

PHYSICS = "physics-9-10"
MATHS = "maths-9-10"
DIST = f"{PHYSICS}/distance-and-displacement"
SPEED = f"{PHYSICS}/speed-and-velocity"
ACCEL = f"{PHYSICS}/acceleration"
LIN = f"{MATHS}/linear-equations-two-variables"


@dataclass
class World:
    a: School
    b: School

    @property
    def maths_student(self) -> uuid.UUID:
        return self.a.student_ids[0]  # 9A maths only

    @property
    def physics_student(self) -> uuid.UUID:
        return self.a.student_ids[3]  # 9B physics only


async def world(db: DbApp) -> World:
    issues, report = await import_tree(DEFAULT_CONTENT_ROOT, db.sessions)
    assert report is not None, [str(i) for i in issues]
    async with db.sessions() as session:
        a = await seed_school(session, "AAA")
        b = await seed_school(session, "BBB")
    return World(a, b)


def keys(data: object) -> set[str]:
    if isinstance(data, dict):
        return set(data) | {k for v in data.values() for k in keys(v)}
    if isinstance(data, list):
        return {k for v in data for k in keys(v)}
    return set()


def url(ref: str, tail: str = "") -> str:
    return f"/api/v1/learn/concepts/{ref}{tail}"


async def get(db: DbApp, user: uuid.UUID, path: str) -> Any:
    r = await db.client.get(path, headers=db.auth(user))
    assert r.status_code == 200, r.text
    return r.json()


async def post(db: DbApp, user: uuid.UUID, path: str, body: dict[str, Any]) -> Any:
    r = await db.client.post(path, json=body, headers=db.auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def statuses(outline: dict[str, Any]) -> dict[str, str | None]:
    return {c["id"]: c["status"] for ch in outline["chapters"] for c in ch["concepts"]}


async def count(db: DbApp, model: Any, **where: Any) -> int:
    async with db.sessions() as session:
        stmt = select(func.count()).select_from(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return int(await session.scalar(stmt) or 0)


# --- answering --------------------------------------------------------------------------------


async def _item_and_seed(db: DbApp, question: dict[str, Any]) -> tuple[Item, int | None]:
    async with db.sessions() as session:
        item = await session.get(Item, uuid.UUID(question["item_id"]))
        assert item is not None
        if question["session_id"] is None:
            return item, question["preview_seed"]
        ps = await session.get(PracticeSession, uuid.UUID(question["session_id"]))
        assert ps is not None
        return item, ps.current_seed


def _option_id(question: dict[str, Any], item: Item, *, correct: bool) -> str:
    texts = {o["id"]: o["text"] for o in item.public["options"]}
    right = texts[item.answer["correct"]]
    for o in question["options"]:
        if (o["text"] == right) == correct:
            return str(o["id"])
    raise AssertionError("no such option")


async def response_for(db: DbApp, question: dict[str, Any], *, correct: bool = True) -> str:
    """A response the server will grade as `correct` for this exact question (item + seed)."""
    item, seed = await _item_and_seed(db, question)
    if item.type.value == "mcq":
        return _option_id(question, item, correct=correct)
    values = sample_answer(item.answer, seed)
    spec = item.answer["spec"]
    if item.type.value == "expression":
        text = answer_text(spec, values)
        return text if correct else f"({text}) + 1"
    shown = grade("numeric", item.answer, values, "0").display_answer
    value = shown.removesuffix(f" {spec.get('unit')}") if spec.get("unit") else shown
    return value if correct else "-987654.321"


async def answer_check(db: DbApp, user: uuid.UUID, ref: str, *, correct: bool = True) -> Any:
    lesson = await get(db, user, url(ref))
    async with db.sessions() as session:
        item = await session.get(Item, uuid.UUID(lesson["check"]["item_id"]))
        assert item is not None
    question = {"options": lesson["check"]["options"]}
    option = _option_id(question, item, correct=correct)
    return await post(db, user, url(ref, "/check"), {"option_id": option, "time_taken_ms": 5000})


async def answer_kp(
    db: DbApp, user: uuid.UUID, ref: str, kp: str, pattern: str = "CC"
) -> list[dict[str, Any]]:
    """Answers `pattern` (C = correct, W = wrong) on one KP; returns each answer's result."""
    out = []
    for c in pattern:
        q = await get(db, user, url(ref, f"/kps/{kp}/question"))
        response = await response_for(db, q, correct=c == "C")
        body = {"position": q["position"], "response": response, "time_taken_ms": 3000}
        out.append(await post(db, user, url(ref, f"/kps/{kp}/answer"), body))
    return out


async def learn_concept(db: DbApp, user: uuid.UUID, ref: str) -> dict[str, Any]:
    """Reads the lesson, answers the check and passes every KP; returns the last answer result."""
    lesson = await get(db, user, url(ref))
    await post(db, user, url(ref, "/progress"), {"step": "intro", "active_seconds": 5})
    if lesson["check"] is not None and lesson["check_result"] is None:
        await answer_check(db, user, ref)
    last: dict[str, Any] = {}
    for kp in lesson["kps"]:
        if kp["status"] == "passed":
            continue
        await post(
            db, user, url(ref, "/progress"), {"step": f"kp:{kp['slug']}", "active_seconds": 5}
        )
        last = (await answer_kp(db, user, ref, kp["slug"]))[-1]
    return last
