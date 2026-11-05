"""What the tutor model sees about one question, and what only the guard knows (spec 009).

`load_content` reads the global content rows for an item (concept, KPs and worked examples, the
key prerequisite). `build_context` renders the per-thread context block (cached) from that plus
the student's attempts at this position, and builds `GuardFacts` (the answer values, never
rendered). The block never contains `item.answer`, the explanation or derived values in before
mode, nor any name, username, school, class or id.
"""

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.guard import ExpressionFact, GuardFacts, NumberFact
from app.ai.safety import scrub_pii
from app.content import params
from app.grading import multistep, units
from app.grading.expression import answer_expr
from app.grading.numeric import to_decimal
from app.models import Concept, ConceptPrereq, Course, Item, KnowledgePoint, KpKeyPrereq
from app.schemas.kp import AnswerResult

Mode = Literal["before", "after"]


@dataclass(frozen=True)
class PrereqInfo:
    concept_id: uuid.UUID
    ref_id: str  # "<course>/<slug>" (the ConceptRef id)
    title: str
    summary: str


@dataclass(frozen=True)
class KpInfo:
    title: str
    worked_example_md: str


@dataclass(frozen=True)
class Content:
    subject: str
    concept_title: str
    concept_summary: str
    concept_intro_md: str
    kps: list[KpInfo]  # the item's KP, or every active KP of the concept (practice items)
    prereq: PrereqInfo | None


@dataclass(frozen=True)
class StepDone:
    """An answered step of a multi-step item (the student has seen its result)."""

    index: int
    response: str
    correct: bool
    display_answer: str


@dataclass
class TutorContext:
    text: str
    facts: GuardFacts
    mode: Mode
    item_type: str
    kp_title: str
    concept_title: str
    prereq: PrereqInfo | None
    solution_shown: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


async def _prereq(
    session: AsyncSession, concept: Concept, kp_ids: list[uuid.UUID]
) -> PrereqInfo | None:
    """The server's pick for rung 2: key prerequisites of the KP(s), else direct prerequisites;
    highest `encompassing_weight` on the concept's prereq edge, ties by the prereq's position."""
    keys = (
        set(
            (
                await session.scalars(
                    select(KpKeyPrereq.concept_id).where(KpKeyPrereq.kp_id.in_(kp_ids))
                )
            ).all()
        )
        if kp_ids
        else set()
    )
    edges = {
        r.prereq_id: r.encompassing_weight
        for r in (
            await session.scalars(
                select(ConceptPrereq).where(ConceptPrereq.concept_id == concept.id)
            )
        ).all()
    }
    candidates = keys or set(edges)
    if not candidates:
        return None
    rows = (
        await session.execute(
            select(Concept, Course.slug)
            .join(Course, Course.id == Concept.course_id)
            .where(Concept.id.in_(candidates))
        )
    ).all()
    if not rows:
        return None
    best, course_slug = min(
        rows, key=lambda r: (-(edges.get(r[0].id) or Decimal(0)), r[0].position, r[0].slug)
    )
    return PrereqInfo(best.id, f"{course_slug}/{best.slug}", best.title, best.summary)


async def load_content(session: AsyncSession, item: Item) -> Content:
    """Global content only (no tenant rows): safe for the eval to call with any session."""
    concept = await session.get(Concept, item.concept_id)
    assert concept is not None
    course = await session.get(Course, concept.course_id)
    assert course is not None
    if item.kp_id is not None:
        kp_rows = [await session.get(KnowledgePoint, item.kp_id)]
    else:
        kp_rows = list(
            (
                await session.scalars(
                    select(KnowledgePoint)
                    .where(
                        KnowledgePoint.concept_id == concept.id, KnowledgePoint.retired_at.is_(None)
                    )
                    .order_by(KnowledgePoint.position)
                )
            ).all()
        )
    kps = [k for k in kp_rows if k is not None]
    return Content(
        subject=course.subject.value,
        concept_title=concept.title,
        concept_summary=concept.summary,
        concept_intro_md=concept.intro_md,
        kps=[KpInfo(k.title, k.worked_example_md) for k in kps],
        prereq=await _prereq(session, concept, [k.id for k in kps]),
    )


# --- rendering -----------------------------------------------------------------------------------


def _render(template: str, values: dict[str, Any]) -> str:
    try:
        return params.render(template, values)
    except KeyError:
        return template


def _esc(text: str) -> str:
    """Student-written text: personal data scrubbed, and it can't close our tags."""
    return scrub_pii(text).replace("<", "&lt;")


def _number_facts(spec: dict[str, Any], values: dict[str, Any]) -> list[NumberFact]:
    try:
        v = to_decimal(params.evaluate(spec["value"], values))
    except Exception:
        return []

    def fact(x: Decimal) -> NumberFact:
        rel, absolute = spec.get("rel_tol"), spec.get("abs_tol")
        return NumberFact(
            value=x,
            mode=spec.get("mode", "exact"),
            sigfigs=spec.get("sigfigs"),
            rel_tol=None if rel is None else Decimal(str(rel)),
            abs_tol=None if absolute is None else Decimal(str(absolute)),
        )

    out = [fact(v)]
    unit = spec.get("unit")
    if unit:
        f = units.si_factor(unit)
        if f is not None and f != 1:
            out.append(fact(v * to_decimal(f)))
    return out


def _add_answer_facts(
    facts: GuardFacts, kind: str, doc: dict[str, Any], values: dict[str, Any]
) -> None:
    spec = doc["spec"]
    if kind == "numeric":
        facts.numbers += _number_facts(spec, values)
    elif kind == "expression":
        try:
            expr = answer_expr(spec, values)
        except Exception:
            return
        variables = tuple(spec["variables"])
        facts.expressions.append(ExpressionFact(expr, variables))
        facts.variables = tuple(dict.fromkeys([*facts.variables, *variables]))
    elif kind == "mcq":
        facts.options += [str(o["text"]) for o in spec["options"]]


def _tests_text(tests: list[dict[str, Any]]) -> list[str]:
    lines = []
    for t in tests:
        args = json.dumps(t.get("args") or [])
        if t.get("expected_stdout") is not None:
            stdin = f", stdin {json.dumps(t['stdin'])}" if t.get("stdin") is not None else ""
            lines.append(f"args {args}{stdin} → prints {json.dumps(t['expected_stdout'])}")
        else:
            lines.append(f"args {args} → returns {json.dumps(t.get('expected'))}")
    return lines


def response_text(item: Item, response: dict[str, Any], step: int | None = None) -> str:
    """A stored attempt response as plain text for the model (MCQ: the option text)."""
    if "code" in response:
        return str(response["code"])
    if "option" in response:
        spec = item.answer["spec"]
        options = (
            spec["steps"][step]["answer"]["mcq"]["options"]
            if step is not None
            else spec.get("options", [])
        )
        text = next(
            (o["text"] for o in options if o["id"] == response["option"]), response["option"]
        )
        return f"chose: {text}"
    raw = str(response.get("raw", ""))
    return f"{raw} {response['unit']}" if response.get("unit") else raw


def build_context(
    content: Content,
    item: Item,
    seed: int | None,
    *,
    mode: Mode,
    steps_done: list[StepDone] | None = None,
    result: AnswerResult | None = None,
    response: str | None = None,
) -> TutorContext:
    """`steps_done`: answered steps (multi-step, before mode). `result` + `response`: after mode,
    exactly what the result panel showed and the student's last answer."""
    steps_done = steps_done or []
    values = dict(params.sample_answer(item.answer, seed))
    public = item.public
    kind = str(public["type"])
    prompt = _render(str(public["prompt"]), values)
    facts = GuardFacts(stem=prompt, exempt_texts=[prompt])

    lines = [
        "<context>",
        f"Subject: {content.subject}",
        f"Concept: {content.concept_title}: {content.concept_summary}",
        f"<concept_intro>\n{content.concept_intro_md}\n</concept_intro>",
    ]
    for kp in content.kps:
        lines.append(f'<worked_example kp="{kp.title}">\n{kp.worked_example_md}\n</worked_example>')
    if content.prereq is not None:
        p = content.prereq
        lines.append(f"<hint_prerequisite>{p.title}: {p.summary}</hint_prerequisite>")
    else:
        lines.append(
            "<hint_prerequisite>none (point to the key idea of the concept's intro)"
            "</hint_prerequisite>"
        )

    lines.append(f'<question type="{kind}" mode="{mode}">')
    lines.append(f"Prompt:\n{prompt}")
    if public.get("unit"):
        lines.append(f"Answer unit: {public['unit']}")
    if kind == "mcq" and mode == "before":
        lines.append("Options (not discussed before answering):")
        lines += [f"- {o['text']}" for o in public.get("options", [])]
    if kind == "multistep":
        done = {s.index: s for s in steps_done}
        for i, step in enumerate(public.get("steps", [])):
            sp = _render(str(step["prompt"]), values)
            facts.exempt_texts.append(sp)
            status = ""
            if i in done:
                d = done[i]
                status = (
                    f" [answered {'correctly' if d.correct else 'incorrectly'}: "
                    f"{_esc(d.response)}; shown answer: {d.display_answer}]"
                )
                facts.exempt_texts.append(d.display_answer)
            elif i == len(steps_done) and mode == "before":
                status = " [current step]"
            lines.append(f"Step {i + 1}: {sp}{status}")
            if step.get("type") == "mcq" and i not in done and mode == "before":
                lines += [f"  - {o['text']}" for o in step.get("options", [])]
    if kind == "code":
        code = public.get("code", {})
        starter = str(code.get("starter", ""))
        visible = _tests_text(code.get("tests", []))
        lines.append(f"Function to write: {code.get('entry')}")
        lines.append(f"Starter code:\n{starter}")
        if visible:
            lines.append("Visible tests:\n" + "\n".join(visible))
        facts.starter = starter
        facts.exempt_texts += [starter, *visible]
        facts.solution = str(item.answer["spec"].get("solution") or "") or None
    lines.append("</question>")

    solution_shown = False
    if mode == "after" and result is not None:
        lines.append("<result>")
        if response is not None:
            lines.append(f"Student's answer:\n{_esc(response)}")
        correct = result.item_correct if result.item_correct is not None else result.correct
        lines.append(f"Result: {'correct' if correct else 'wrong'}")
        if result.step_results:
            for i, s in enumerate(result.step_results):
                lines.append(
                    f"Step {i + 1}: {'correct' if s.correct else 'wrong'}; "
                    f"shown answer: {s.display_answer}"
                )
        elif result.display_answer:
            lines.append(f"Shown answer: {result.display_answer}")
        if result.misconception is not None:
            lines.append(f"Misconception: {result.misconception.title}")
        if result.note:
            lines.append(f"Note: {result.note}")
        if result.tests:
            for t in result.tests:
                exp = f", expected {t.expected}" if t.expected is not None else ""
                label = "visible" if t.visible else "hidden"
                lines.append(f"Test ({label}) args {t.args}: {t.status}{exp}, got {_esc(t.got)}")
        if result.explanation_md:
            lines.append(f"Explanation:\n{result.explanation_md}")
        if result.solution:
            solution_shown = True
            lines.append(f"Solution shown to the student:\n{result.solution}")
        lines.append("</result>")
    lines.append("</context>")

    if mode == "before":
        if kind == "multistep":
            for i in range(len(steps_done), multistep.step_count(item.answer)):
                _add_answer_facts(
                    facts,
                    multistep.step_type(item.answer, i),
                    multistep.step_answer_doc(item.answer, i),
                    values,
                )
        elif kind in ("numeric", "expression", "mcq"):
            _add_answer_facts(facts, kind, item.answer, values)
        for name in item.answer.get("derived") or {}:
            if name in values:
                facts.numbers.append(NumberFact(to_decimal(values[name])))

    kp_title = content.kps[0].title if len(content.kps) == 1 else content.concept_title
    return TutorContext(
        text="\n".join(lines),
        facts=facts,
        mode=mode,
        item_type=kind,
        kp_title=kp_title,
        concept_title=content.concept_title,
        prereq=content.prereq,
        solution_shown=solution_shown,
    )
