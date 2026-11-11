"""Review pack (spec 013): one self-contained HTML file per course, every answer included.

For subject teachers who don't read YAML. Pure: `build_review_pack` takes a loaded (and validated)
`ContentBundle` and returns HTML. Answers are shown the way students see them: each item is split
the way the importer stores it (`hashing.split_item`), sampled with the students' code
(`params.sample_answer` + `params.render`) and displayed with the grading helpers.

Content text is never built into HTML here: it goes into a `<script type="application/json">`
block (with `<`, `>`, `&` escaped) and the page's script renders it with marked + KaTeX, escaping
raw HTML like the app does. The pack contains answers and hidden tests by design: it is a local,
gitignored file, never served by the app.
"""

import base64
import json
import mimetypes
from decimal import Decimal
from pathlib import Path
from typing import Any

import sympy

from app.content import params
from app.content.hashing import item_texts, split_item
from app.content.loader import ContentBundle, LoadedConcept, LoadedCourse, image_refs
from app.content.schema import CodeAnswer, Item, McqAnswer, MultistepAnswer, StepAnswer
from app.grading.expression import answer_expr
from app.grading.numeric import display_value, to_decimal
from app.models.content import ItemKind

# Pinned like frontend/package.json (marked: the lockfile's version).
KATEX = "https://cdn.jsdelivr.net/npm/katex@0.19.1/dist"
MARKED = "https://cdn.jsdelivr.net/npm/marked@16.4.2/lib/marked.umd.js"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.esm.min.mjs"

SEED_NOTE = (
    "Param questions are shown for sample seeds 1-{n}. Students get random seeds, "
    "so the numbers a student saw may differ."
)


# --- answers --------------------------------------------------------------------------------------


def _numeric(spec: dict[str, Any], values: dict[str, Any]) -> str:
    v: Decimal = to_decimal(params.evaluate(spec["value"], values))
    text = display_value(spec, v)
    return f"{text} {spec['unit']}" if spec.get("unit") else text


def _expression(spec: dict[str, Any], values: dict[str, Any]) -> str:
    return f"${sympy.latex(answer_expr(spec, values))}$"


def _mcq_answer(spec: dict[str, Any]) -> str:
    correct = next((o for o in spec["options"] if o.get("correct")), None)
    return "" if correct is None else f"({correct['id']}) {correct['text']}"


def _answer(kind: str, spec: dict[str, Any], values: dict[str, Any]) -> str:
    if kind == "numeric":
        return _numeric(spec, values)
    if kind == "expression":
        return _expression(spec, values)
    return _mcq_answer(spec)


def _render(text: str | None, values: dict[str, Any]) -> str | None:
    if text is None:
        return None
    try:
        return params.render(text, values)
    except KeyError:
        return text


def _sample(item: Item, answer: dict[str, Any], seed: int | None) -> dict[str, Any]:
    out: dict[str, Any] = {"seed": seed}
    try:
        values = params.sample_answer(answer, seed)
        out["values"] = {k: params.format_number(v) for k, v in values.items()}
        out["prompt"] = _render(item.prompt, values)
        out["explanation"] = _render(item.explanation, values)
        spec = answer["spec"]
        if item.type.value == "multistep":
            out["steps"] = [
                {
                    "prompt": _render(step["prompt"], values),
                    "type": StepAnswer.model_validate(step["answer"]).type.value,
                    "answer": _step_answer(step["answer"], values),
                }
                for step in spec["steps"]
            ]
        else:
            out["answer"] = _answer(item.type.value, spec, values)
    except Exception as exc:  # a broken item still gets a pack; the reviewer sees why
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _step_answer(step: dict[str, Any], values: dict[str, Any]) -> str:
    kind, spec = next((k, v) for k, v in step.items() if v is not None)
    return _answer(kind, spec, values)


def _options(spec: McqAnswer, titles: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "id": o.id,
            "text": o.text,
            "correct": o.correct,
            "misconception": (
                None
                if o.misconception is None
                else {"id": o.misconception, "title": titles.get(o.misconception, "?")}
            ),
        }
        for o in spec.options
    ]


def _item(item: Item, kind: ItemKind, seeds: int, titles: dict[str, str]) -> dict[str, Any]:
    _, answer = split_item(item)
    spec = item.spec
    out: dict[str, Any] = {
        "id": item.id,
        "kind": kind.value,
        "type": item.type.value,
        "bloom": item.bloom.value,
        "expected_minutes": item.expected_minutes,
        "pool_weight": 2 if item.has_params else 1,
        "prompt": item.prompt,
        "explanation": item.explanation,
        "params": answer["params"],
        "constraints": answer["constraints"],
        "derived": answer["derived"],
    }
    if isinstance(spec, CodeAnswer):
        out["code"] = {
            "entry": spec.entry,
            "starter": spec.starter,
            "solution": spec.solution,
            "time_limit_ms": spec.time_limit_ms,
            "tests": [_test(t) for t in spec.tests],
        }
        out["samples"] = []
        return out
    if isinstance(spec, McqAnswer):
        out["options"] = _options(spec, titles)
    elif isinstance(spec, MultistepAnswer):
        out["step_specs"] = [
            {
                "type": s.answer.type.value,
                "spec": s.answer.spec.model_dump(mode="json", exclude_defaults=True),
                "options": (_options(s.answer.mcq, titles) if s.answer.mcq is not None else None),
            }
            for s in spec.steps
        ]
    else:
        out["answer_spec"] = spec.model_dump(mode="json", exclude_defaults=True)
    seed_list: list[int | None] = list(range(1, seeds + 1)) if item.has_params else [None]
    out["samples"] = [_sample(item, answer, s) for s in seed_list]
    return out


def _test(test: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"args": test.args}
    if test.stdin is not None:
        out["stdin"] = test.stdin
    if test.is_stdout:
        out["expected_stdout"] = test.expected_stdout
    else:
        out["expected"] = test.expected
    out["visible"] = test.visible
    return out


# --- images ---------------------------------------------------------------------------------------


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".svg":
        mime = "image/svg+xml"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _images(concept: LoadedConcept) -> dict[str, str]:
    texts: list[str | None] = list(concept.markdown.values())
    f = concept.file
    for item in [f.misconception_check, *(i for kp in f.kps for i in kp.items), *f.practice]:
        texts += item_texts(item)
    out: dict[str, str] = {}
    root = concept.dir.resolve()
    for text in texts:
        for ref in image_refs(text or ""):
            path = (concept.dir / ref).resolve()
            if ref not in out and path.is_file() and path.is_relative_to(root):
                out[ref] = _data_uri(path)
    return dict(sorted(out.items()))


# --- the document ---------------------------------------------------------------------------------


def _concept(concept: LoadedConcept, seeds: int, titles: dict[str, str]) -> dict[str, Any]:
    f = concept.file
    return {
        "id": f.id,
        "title": f.title,
        "summary": f.summary,
        "prereqs": [{"concept": p.concept, "weight": p.weight} for p in f.prereqs],
        "intro": concept.markdown.get(f.intro, ""),
        "check": _item(f.misconception_check, ItemKind.misconception_check, seeds, titles),
        "kps": [
            {
                "id": kp.id,
                "title": kp.title,
                "key_prereqs": list(kp.key_prereqs),
                "worked_example": concept.markdown.get(kp.worked_example, ""),
                "items": [_item(i, ItemKind.kp_question, seeds, titles) for i in kp.items],
            }
            for kp in f.kps
        ],
        "practice": [_item(i, ItemKind.practice, seeds, titles) for i in f.practice],
        "images": _images(concept),
    }


def _course(bundle: ContentBundle, course_id: str) -> LoadedCourse:
    for course in bundle.courses:
        if course.file.id == course_id:
            return course
    raise KeyError(course_id)


def pack_data(
    bundle: ContentBundle,
    course_id: str,
    *,
    seeds: int,
    generated: str | None = None,
    sha: str | None = None,
) -> dict[str, Any]:
    """The pack as JSON-ready data (what the page renders). `KeyError` for an unknown course."""
    course = _course(bundle, course_id)
    titles = {m.id: m.title for m in course.misconceptions}
    concepts = course.concepts
    items = sum(
        1 + sum(len(kp.items) for kp in c.file.kps) + len(c.file.practice) for c in concepts
    )
    return {
        "meta": {"generated": generated, "sha": sha},
        "course": {
            "id": course.file.id,
            "title": course.file.title,
            "subject": course.file.subject.value,
        },
        "seeds": seeds,
        "seed_note": SEED_NOTE.format(n=seeds),
        "counts": {"chapters": len(course.chapters), "concepts": len(concepts), "items": items},
        "misconceptions": [
            {"id": m.id, "title": m.title, "description": m.description}
            for m in course.misconceptions
        ],
        "chapters": [
            {
                "id": ch.file.id,
                "title": ch.file.title,
                "grade": ch.file.grade,
                "concepts": [_concept(c, seeds, titles) for c in ch.concepts],
            }
            for ch in course.chapters
        ],
    }


def sample_errors(bundle: ContentBundle, course_id: str, *, seeds: int) -> int:
    """How many items of the course failed to sample (shown as errors in the pack)."""
    data = pack_data(bundle, course_id, seeds=seeds)
    items = [
        item
        for ch in data["chapters"]
        for c in ch["concepts"]
        for item in [c["check"], *(i for kp in c["kps"] for i in kp["items"]), *c["practice"]]
    ]
    return sum(any("error" in s for s in item["samples"]) for item in items)


def _json_block(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=1)
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def build_review_pack(
    bundle: ContentBundle,
    course_id: str,
    *,
    seeds: int,
    generated: str | None = None,
    sha: str | None = None,
) -> str:
    """The self-contained HTML review pack for one course."""
    data = pack_data(bundle, course_id, seeds=seeds, generated=generated, sha=sha)
    return (
        TEMPLATE.replace("%KATEX%", KATEX)
        .replace("%MARKED%", MARKED)
        .replace("%MERMAID%", MERMAID)
        .replace("%DATA%", _json_block(data))
    )


TEMPLATE = (Path(__file__).with_name("review_pack.html")).read_text(encoding="utf-8")
