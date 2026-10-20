"""Canonical JSON + sha256 per imported row, and the public/answer split of items.

`split_item` is the never-to-client rule in code: `public` is all a client may ever see; everything
else (answer spec, params, constraints, derived values, explanation, solution, hidden tests) goes in
`answer`, which never leaves the server.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from app.content.loader import LoadedConcept, image_refs
from app.content.schema import (
    ChapterFile,
    CodeAnswer,
    CourseFile,
    Item,
    Kp,
    McqAnswer,
    Misconception,
    MultistepAnswer,
    NumericAnswer,
    StepAnswer,
)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def _dump(model: Any) -> Any:
    # exclude_defaults: adding an optional field to the schema later doesn't re-version every row.
    return model.model_dump(mode="json", exclude_defaults=True)


def image_hashes(concept_dir: Path, *texts: str | None) -> dict[str, str]:
    """sha256 of each existing image referenced from `texts`, keyed by its relative path."""
    out: dict[str, str] = {}
    for text in texts:
        for ref in image_refs(text or ""):
            path = (concept_dir / ref).resolve()
            if path.is_file() and path.is_relative_to(concept_dir.resolve()):
                out[ref] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def item_texts(item: Item) -> list[str | None]:
    """Every Markdown string in an item (prompt, explanation, step prompts, option texts)."""
    texts: list[str | None] = [item.prompt, item.explanation]
    spec = item.spec
    if isinstance(spec, MultistepAnswer):
        texts += [s.prompt for s in spec.steps]
        texts += [o.text for s in spec.steps if s.answer.mcq for o in s.answer.mcq.options]
    if isinstance(spec, McqAnswer):
        texts += [o.text for o in spec.options]
    return texts


# --- per-row hashes (authored content only: never position or parent) -----------------------------


def course_hash(course: CourseFile) -> str:
    return sha256({"id": course.id, "title": course.title, "subject": course.subject.value})


def chapter_hash(chapter: ChapterFile) -> str:
    return sha256({"id": chapter.id, "title": chapter.title, "grade": chapter.grade})


def misconception_hash(m: Misconception) -> str:
    return sha256(_dump(m))


def concept_hash(concept: LoadedConcept) -> str:
    f = concept.file
    intro = concept.markdown.get(f.intro, "")
    return sha256(
        {
            "id": f.id,
            "title": f.title,
            "summary": f.summary,
            "prereqs": [_dump(p) for p in f.prereqs],
            "intro": intro,
            "images": image_hashes(concept.dir, intro),
        }
    )


def kp_hash(concept: LoadedConcept, kp: Kp) -> str:
    worked = concept.markdown.get(kp.worked_example, "")
    return sha256(
        {
            "id": kp.id,
            "title": kp.title,
            "key_prereqs": kp.key_prereqs,
            "worked_example": worked,
            "images": image_hashes(concept.dir, worked),
        }
    )


def item_hash(concept: LoadedConcept, item: Item) -> str:
    return sha256({"item": _dump(item), "images": image_hashes(concept.dir, *item_texts(item))})


# --- public / answer split ------------------------------------------------------------------------


def _public_options(mcq: McqAnswer) -> dict[str, Any]:
    return {"options": [{"id": o.id, "text": o.text} for o in mcq.options], "shuffle": mcq.shuffle}


def _public_step(step: StepAnswer) -> dict[str, Any]:
    out: dict[str, Any] = {"type": step.type.value}
    if step.numeric is not None and step.numeric.unit:
        out["unit"] = step.numeric.unit
    if step.mcq is not None:
        out.update(_public_options(step.mcq))
    return out


def _public_test(test: Any) -> dict[str, Any]:
    if test.is_stdout:
        out = {"args": test.args, "expected_stdout": test.expected_stdout}
        return out if test.stdin is None else out | {"stdin": test.stdin}
    return {"args": test.args, "expected": test.expected}


def split_item(item: Item) -> tuple[dict[str, Any], dict[str, Any]]:
    """(`public`, `answer`) JSON documents for one item."""
    spec = item.spec
    public: dict[str, Any] = {
        "type": item.type.value,
        "prompt": item.prompt,
        "has_params": item.has_params,
    }
    answer: dict[str, Any] = {
        "spec": spec.model_dump(mode="json"),
        "params": {k: _dump(v) for k, v in item.params.items()},
        "constraints": list(item.constraints),
        "derived": dict(item.derived),
        "explanation": item.explanation,
    }
    if isinstance(spec, NumericAnswer) and spec.unit:
        public["unit"] = spec.unit
    elif isinstance(spec, McqAnswer):
        public.update(_public_options(spec))
        answer["correct"] = next((o.id for o in spec.options if o.correct), None)
        answer["misconceptions"] = {o.id: o.misconception for o in spec.options if o.misconception}
    elif isinstance(spec, MultistepAnswer):
        public["steps"] = [{"prompt": s.prompt} | _public_step(s.answer) for s in spec.steps]
    elif isinstance(spec, CodeAnswer):
        public["code"] = {
            "entry": spec.entry,
            "starter": spec.starter,
            "tests": [_public_test(t) for t in spec.tests if t.visible],
        }
    return public, answer
