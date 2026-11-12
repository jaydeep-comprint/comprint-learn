"""Answers for the load test, worked out the way the DB tests do (tests/learn_helpers.py).

Locust reads the session's `current_seed` and the item's `answer` straight from the test database
and derives the expected answer with the app's own code (`app.content.params.sample_answer`,
`app.grading`), so no API change is needed and no answer key crosses the API.

One shared database connection (pg8000: pure Python, so it cooperates with gevent) behind a lock:
the Supabase Session pooler pins a server connection per client, and the API needs those.
"""

import json
import random
import ssl
from typing import Any
from urllib.parse import unquote, urlsplit

from app.content import code_runner
from app.content.params import sample_answer
from app.content.schema import CodeAnswer
from app.grading import grade, multistep
from app.grading.expression import answer_text

WRONG_NUMBER = "-987654.321"


def connect(url: str) -> Any:
    import pg8000.native

    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://"))
    local = parts.hostname in {"localhost", "127.0.0.1"}
    return pg8000.native.Connection(
        user=unquote(parts.username or "postgres"),
        password=unquote(parts.password or ""),
        host=parts.hostname or "localhost",
        port=parts.port or 5432,
        database=(parts.path or "/postgres").lstrip("/") or "postgres",
        ssl_context=None if local else ssl.create_default_context(),
        timeout=30,
    )


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class AnswerKey:
    """Item keys (loaded once) + the current seed of a session (one query per question)."""

    def __init__(self, url: str) -> None:
        from gevent.lock import Semaphore

        self.url = url
        self.lock = Semaphore()
        self.conn: Any = None
        self.items: dict[str, dict[str, Any]] = {}
        self.code_outputs: dict[tuple[str, bool], list[dict[str, object]]] = {}

    def _ensure(self) -> None:
        """Connect and load every item's key once (641 rows of global content)."""
        if self.conn is None:
            self.conn = connect(self.url)
            rows = self.conn.run("select id::text, type::text, answer, public from item")
            self.items = {
                r[0]: {"type": r[1], "answer": _json(r[2]), "public": _json(r[3])} for r in rows
            }

    def _run(self, sql: str, **params: Any) -> list[list[Any]]:
        with self.lock:
            self._ensure()
            result: list[list[Any]] = self.conn.run(sql, **params)
            return result

    def seed_for(self, session_id: str) -> tuple[str | None, int | None]:
        rows = self._run(
            "select current_item_id::text, current_seed from practice_session"
            " where id = cast(:id as uuid)",
            id=session_id,
        )
        return (rows[0][0], rows[0][1]) if rows else (None, None)

    def fields(self, question: dict[str, Any], *, correct: bool) -> dict[str, Any] | None:
        """The answer fields for this question, or None when the session moved on."""
        session_id = question.get("session_id")
        if not session_id:
            return None
        item_id, seed = self.seed_for(session_id)
        if item_id is None or item_id != question["item_id"]:
            return None
        item = self.items[item_id]
        values = sample_answer(item["answer"], seed)
        return {"session_id": session_id} | self._body(item_id, item, values, question, correct)

    def _body(
        self,
        item_id: str,
        item: dict[str, Any],
        values: dict[str, Any],
        q: dict[str, Any],
        correct: bool,
    ) -> dict[str, Any]:
        kind = item["type"]
        if kind == "code":
            return self._code(item_id, item, correct)
        if kind == "multistep":
            step = q["step"]
            doc = multistep.step_answer_doc(item["answer"], step)
            options = q["steps"][step]["options"]
            authored = item["public"]["steps"][step].get("options")
            step_kind = multistep.step_type(item["answer"], step)
            return {"step": step} | quick(
                step_kind, doc, values, options, authored, correct=correct
            )
        return quick(
            kind,
            item["answer"],
            values,
            q.get("options"),
            item["public"].get("options"),
            correct=correct,
        )

    def _code(self, item_id: str, item: dict[str, Any], correct: bool) -> dict[str, Any]:
        spec = dict(item["answer"]["spec"])
        spec["tests"] = [
            {k: v for k, v in t.items() if not (k == "expected" and t.get("expected_stdout"))}
            for t in spec["tests"]
        ]
        model = CodeAnswer.model_validate(spec)
        source = model.solution if correct else model.starter
        key = (item_id, correct)
        if key not in self.code_outputs:  # a canned output set per item: run once, reuse
            self.code_outputs[key] = code_runner.run_outputs(model, source=source)
        return {"code": source, "outputs": self.code_outputs[key]}

    def option_for_check(self, check: dict[str, Any], *, correct: bool) -> str:
        """The Learn check's option id (an MCQ shown in a per-student order)."""
        with self.lock:
            self._ensure()
        item = self.items[check["item_id"]]
        return option_id(
            check["options"], item["public"]["options"], item["answer"]["correct"], correct=correct
        )


def option_id(
    options: list[dict[str, Any]], authored: list[dict[str, Any]], right_id: str, *, correct: bool
) -> str:
    """Positional ids are shuffled per student: match on the option text."""
    right = {o["id"]: o["text"] for o in authored}[right_id]
    candidates = [str(o["id"]) for o in options if (o["text"] == right) == correct]
    return candidates[0] if correct else random.choice(candidates)


def quick(
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
        return {"response": option_id(options, authored, doc["correct"], correct=correct)}
    spec = doc["spec"]
    if kind == "expression":
        text = answer_text(spec, values)
        return {"response": text if correct else f"({text}) + 1"}
    unit = spec.get("unit")
    shown = grade("numeric", doc, values, "0", unit=unit).display_answer
    value = shown.removesuffix(f" {unit}") if unit else shown
    out: dict[str, Any] = {"response": value if correct else WRONG_NUMBER}
    if unit:
        out["unit"] = unit
    return out
