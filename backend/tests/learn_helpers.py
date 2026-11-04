"""Shared helpers for the Learn / KP DB tests: the imported sample content, two schools, and
drivers that answer questions correctly (or not) by reading the answer key server side."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.cli import DEFAULT_CONTENT_ROOT
from app.content import code_runner
from app.content.importer import import_tree
from app.content.params import sample_answer
from app.content.schema import CodeAnswer
from app.grading import grade, multistep
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


def _option_id(
    options: list[dict[str, Any]], authored: list[dict[str, Any]], right_id: str, *, correct: bool
) -> str:
    texts = {o["id"]: o["text"] for o in authored}
    right = texts[right_id]
    for o in options:
        if (o["text"] == right) == correct:
            return str(o["id"])
    raise AssertionError("no such option")


def code_spec(answer: dict[str, Any]) -> CodeAnswer:
    """The stored code spec as the schema model (stdout tests have no `expected` key)."""
    spec = dict(answer["spec"])
    spec["tests"] = [
        {k: v for k, v in t.items() if not (k == "expected" and t.get("expected_stdout"))}
        for t in spec["tests"]
    ]
    return CodeAnswer.model_validate(spec)


def _quick(
    kind: str,
    doc: dict[str, Any],
    values: dict[str, Any],
    options: list[dict[str, Any]] | None,
    authored: list[dict[str, Any]] | None,
    *,
    correct: bool,
) -> dict[str, Any]:
    if kind == "mcq":
        assert options is not None and authored is not None
        return {"response": _option_id(options, authored, doc["correct"], correct=correct)}
    spec = doc["spec"]
    if kind == "expression":
        text = answer_text(spec, values)
        return {"response": text if correct else f"({text}) + 1"}
    unit = spec.get("unit")
    shown = grade("numeric", doc, values, "0", unit=unit).display_answer
    value = shown.removesuffix(f" {unit}") if unit else shown
    out: dict[str, Any] = {"response": value if correct else "-987654.321"}
    if unit:
        out["unit"] = unit
    return out


async def answer_fields(
    db: DbApp, question: dict[str, Any], *, correct: bool = True
) -> dict[str, Any]:
    """Answer fields (`response`, `unit`, `step`, `code` + `outputs`) the server will grade as
    `correct` for this exact question (item + seed; multistep: its current step)."""
    item, seed = await _item_and_seed(db, question)
    kind = item.type.value
    values = sample_answer(item.answer, seed)
    session = {"session_id": question["session_id"]} if question.get("session_id") else {}
    return session | await _answer_body(item, kind, values, question, correct=correct)


async def _answer_body(
    item: Item, kind: str, values: dict[str, Any], question: dict[str, Any], *, correct: bool
) -> dict[str, Any]:
    if kind == "code":
        spec = code_spec(item.answer)
        source = spec.solution if correct else spec.starter
        return {"code": source, "outputs": code_runner.run_outputs(spec, source=source)}
    if kind == "multistep":
        step = question["step"]
        doc = multistep.step_answer_doc(item.answer, step)
        options = question["steps"][step]["options"]
        authored = item.public["steps"][step].get("options")
        step_kind = multistep.step_type(item.answer, step)
        return {"step": step} | _quick(step_kind, doc, values, options, authored, correct=correct)
    return _quick(
        kind, item.answer, values, question["options"], item.public.get("options"), correct=correct
    )


async def response_for(db: DbApp, question: dict[str, Any], *, correct: bool = True) -> str:
    """Just the `response` text (quick-check items)."""
    return str((await answer_fields(db, question, correct=correct))["response"])


async def answer_question(
    db: DbApp, user: uuid.UUID, path: str, question: dict[str, Any], *, correct: bool = True
) -> dict[str, Any]:
    """Answers the question completely (every remaining step of a multi-step item, all
    `correct` or all wrong); returns the last result."""
    while True:
        body = {"position": question["position"], "time_taken_ms": 3000}
        body |= await answer_fields(db, question, correct=correct)
        result: dict[str, Any] = await post(db, user, f"{path}/answer", body)
        if result.get("item_done", True):
            return result
        question = await get(db, user, f"{path}/question")


async def answer_check(db: DbApp, user: uuid.UUID, ref: str, *, correct: bool = True) -> Any:
    lesson = await get(db, user, url(ref))
    async with db.sessions() as session:
        item = await session.get(Item, uuid.UUID(lesson["check"]["item_id"]))
        assert item is not None
    option = _option_id(
        lesson["check"]["options"], item.public["options"], item.answer["correct"], correct=correct
    )
    return await post(db, user, url(ref, "/check"), {"option_id": option, "time_taken_ms": 5000})


async def answer_kp(
    db: DbApp, user: uuid.UUID, ref: str, kp: str, pattern: str = "CC"
) -> list[dict[str, Any]]:
    """Answers `pattern` (C = correct, W = wrong) on one KP; returns each answer's result."""
    out = []
    path = url(ref, f"/kps/{kp}")
    for c in pattern:
        q = await get(db, user, f"{path}/question")
        out.append(await answer_question(db, user, path, q, correct=c == "C"))
    return out


async def pass_practice(db: DbApp, user: uuid.UUID, ref: str) -> dict[str, Any]:
    """Passes the lesson's Practice step (every step / test right); returns the last result."""
    path = url(ref, "/practice")
    q = await get(db, user, f"{path}/question")
    return await answer_question(db, user, path, q)


async def learn_concept(db: DbApp, user: uuid.UUID, ref: str) -> dict[str, Any]:
    """Reads the lesson, answers the check, passes every KP and the Practice step; returns the
    last answer result."""
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
    if lesson["practice"]["status"] == "pending":
        last = await pass_practice(db, user, ref)
    return last
