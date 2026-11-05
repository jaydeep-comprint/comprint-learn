"""The tutor eval runner (spec 009): `uv run app tutor eval [--runs 3] [--case ID]`.

Builds each case's context from imported content (read-only; no student rows), runs the same
`run_turn` the service uses (prompt → model → guard → retry/fallback) `runs` times, then grades
every final reply with the deterministic guard and a Sonnet judge. Pass = no answer / step leak or
confirmation in any run, and every `expect_category` met. Needs `DEEPSEEK_API_KEY`.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import guard, limits, safety
from app.ai.client import ChatClient, DeepSeekTutorClient, TutorCall, TutorUnavailable
from app.ai.context import StepDone, TutorContext, build_context, load_content
from app.ai.eval.judge import Verdict, judge
from app.ai.tutor_turn import TranscriptLine, TurnRequest, TurnResult, run_turn
from app.content import params
from app.grading import grade, multistep
from app.grading.expression import answer_text
from app.models import Concept, Course, Item, KnowledgePoint
from app.schemas.kp import AnswerResult

CASES = Path(__file__).with_name("cases.yaml")


@dataclass
class Case:
    id: str
    item: str
    request: dict[str, Any]
    seed: int | None = None
    mode: str = "before"
    history: list[dict[str, Any]] = field(default_factory=list)
    draft: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    expect_category: str | list[str] | None = None  # one, or any of several
    expect_scrubbed: list[str] = field(default_factory=list)


@dataclass
class RunOutcome:
    reply: str
    status: str
    category: str | None
    guard_leaks: list[guard.Leak]
    verdict: Verdict
    category_ok: bool
    scrubbed_ok: bool
    tutor_in: int
    tutor_out: int
    error: str | None = None  # provider or judge failed 3 times: the run is unverified
    caught: list[str] = field(default_factory=list)  # guard catches before retry / fallback

    @property
    def failed(self) -> bool:
        if self.error is not None:
            return False  # counted separately: the run is incomplete, not a leak
        return (
            bool(self.guard_leaks)
            or self.verdict.leaked
            or not self.category_ok
            or not self.scrubbed_ok
        )


class RecordingClient:
    """Wraps the real client to check what reached the model (PII cases)."""

    def __init__(self, inner: DeepSeekTutorClient) -> None:
        self.inner = inner
        self.sent: list[str] = []

    async def create(self, request: dict[str, Any]) -> TutorCall:
        self.sent.append(repr(request["messages"]))
        return await self.inner.create(request)


def load_cases(path: Path = CASES) -> list[Case]:
    return [Case(**raw) for raw in yaml.safe_load(path.read_text())]


async def _item(session: AsyncSession, ref: str) -> Item:
    course, concept, kp, slug = ref.split("/")
    stmt = (
        select(Item)
        .join(Concept, Concept.id == Item.concept_id)
        .join(Course, Course.id == Concept.course_id)
        .where(Course.slug == course, Concept.slug == concept, Item.slug == slug)
        .where(Item.retired_at.is_(None))
    )
    if kp == "practice":
        stmt = stmt.where(Item.kp_id.is_(None))
    else:
        stmt = stmt.join(KnowledgePoint, KnowledgePoint.id == Item.kp_id).where(
            KnowledgePoint.slug == kp
        )
    item = await session.scalar(stmt)
    if item is None:
        raise LookupError(f"no item {ref} (run `make content-import` first)")
    return item


def _grade_part(item: Item, index: int | None, values: dict[str, Any], a: dict[str, Any]) -> Any:
    if index is None:
        kind, doc = item.type.value, item.answer
    else:
        kind, doc = (
            multistep.step_type(item.answer, index),
            multistep.step_answer_doc(item.answer, index),
        )
    if kind not in ("numeric", "expression"):
        raise ValueError("eval attempts support numeric / expression answers only")
    return grade(kind, doc, values, str(a.get("raw", "")), unit=a.get("unit"))


def true_answer(item: Item, seed: int | None) -> str:
    """The answer, for the judge only."""
    values = params.sample_answer(item.answer, seed)
    kind = item.type.value
    if kind == "code":
        return str(item.answer["spec"]["solution"])
    if kind == "mcq":
        return str(next(o["text"] for o in item.answer["spec"]["options"] if o.get("correct")))
    if kind == "expression":
        return answer_text(item.answer["spec"], values)
    if kind == "multistep":
        parts = []
        for i in range(multistep.step_count(item.answer)):
            doc = multistep.step_answer_doc(item.answer, i)
            k = multistep.step_type(item.answer, i)
            unit = doc["spec"].get("unit")
            shown = grade(k, doc, values, "0", unit=unit).display_answer if k != "mcq" else "?"
            parts.append(f"step {i + 1}: {shown}")
        shown_derived = {k: str(values[k]) for k in item.answer.get("derived") or {}}
        return "; ".join(parts) + f" (intermediate values: {shown_derived})"
    unit = item.answer["spec"].get("unit")
    return grade(kind, item.answer, values, "0", unit=unit).display_answer


async def build_case_context(session: AsyncSession, case: Case) -> tuple[Item, TutorContext]:
    item = await _item(session, case.item)
    content = await load_content(session, item)
    values = params.sample_answer(item.answer, case.seed)
    if case.mode == "after":
        a = case.attempts[-1]
        g = _grade_part(item, None, values, a)
        text_ = item.answer.get("explanation")
        result = AnswerResult(
            correct=g.correct,
            display_answer=g.display_answer,
            explanation_md=params.render(text_, values) if text_ else None,
            misconception=None,
            note=g.note,
            session_status="failed",
            already_answered=False,
            results=[g.correct],
            item_correct=g.correct,
        )
        raw = f"{a.get('raw', '')} {a.get('unit') or ''}".strip()
        return item, build_context(
            content, item, case.seed, mode="after", result=result, response=raw
        )
    steps = [
        StepDone(
            i,
            str(a.get("raw", "")),
            (g := _grade_part(item, i, values, a)).correct,
            g.display_answer,
        )
        for i, a in enumerate(case.attempts)
    ]
    return item, build_context(content, item, case.seed, mode="before", steps_done=steps)


def _transcript(case: Case) -> list[TranscriptLine]:
    return [
        TranscriptLine(h["role"], h["kind"], h.get("rung"), h.get("text")) for h in case.history
    ]


def _request(case: Case) -> TurnRequest:
    draft = safety.scrub_pii(case.draft) if case.draft else None
    if "hint" in case.request:
        return TurnRequest("hint", rung=int(case.request["hint"]), draft=draft)
    return TurnRequest("chat", text=safety.scrub_pii(str(case.request["chat"])), draft=draft)


def _category_ok(case: Case, turn: TurnResult) -> bool:
    if case.expect_category is None:
        return True
    allowed = (
        [case.expect_category] if isinstance(case.expect_category, str) else case.expect_category
    )
    got = "safety" if turn.status == "safety" else turn.category
    if "ok" in allowed and turn.status == "fallback":
        return False  # a canned fallback isn't the helpful reply the case expects
    return got in allowed


ATTEMPTS = 3  # a run is retried on provider errors (timeouts, 5xx) before it's an error


async def _one_run(
    case: Case,
    ctx: TutorContext,
    req: TurnRequest,
    answer: str,
    tutor: DeepSeekTutorClient,
    judge_client: ChatClient,
    tutor_model: str,
    judge_model: str,
) -> tuple[RunOutcome, int, int]:
    error = "unknown"
    for _ in range(ATTEMPTS):
        try:
            recorder = RecordingClient(tutor)
            turn = await run_turn(ctx, _transcript(case), req, recorder, tutor_model)
            limit = limits.HINT_WORDS if req.kind == "hint" else limits.CHAT_WORDS
            leaks = guard.check(
                turn.text,
                ctx.facts,
                mode=ctx.mode,
                word_limit=limit,
                draft=req.draft,
                solution_shown=ctx.solution_shown,
            )
            verdict = await judge(
                judge_client,
                judge_model,
                context=ctx.text,
                true_answer=answer,
                mode=ctx.mode,
                request=f"hint rung {req.rung}" if req.kind == "hint" else str(req.text),
                reply=turn.text,
            )
        except TutorUnavailable as exc:
            error = str(exc)
            continue
        scrubbed = all(s not in sent for s in case.expect_scrubbed for sent in recorder.sent)
        outcome = RunOutcome(
            turn.text,
            turn.status,
            turn.category,
            leaks,
            verdict,
            _category_ok(case, turn),
            scrubbed,
            turn.input_tokens + turn.cache_read_tokens + turn.cache_write_tokens,
            turn.output_tokens,
            caught=[f"{leak.kind}: {leak.detail}" for leak in turn.caught],
        )
        if verdict.unreadable:
            error = "judge output unreadable"
            continue
        return outcome, verdict.input_tokens, verdict.output_tokens
    blank = Verdict(False, False, False, False, False, f"provider error: {error}")
    return RunOutcome("", "error", None, [], blank, True, True, 0, 0, error=error), 0, 0


async def run_case(
    session: AsyncSession,
    case: Case,
    tutor: DeepSeekTutorClient,
    judge_client: ChatClient,
    tutor_model: str,
    judge_model: str,
    runs: int,
) -> tuple[list[RunOutcome], int, int]:
    item, ctx = await build_case_context(session, case)
    answer = true_answer(item, case.seed)
    req = _request(case)
    outcomes = []
    judge_in = judge_out = 0
    for _ in range(runs):
        outcome, ji, jo = await _one_run(
            case, ctx, req, answer, tutor, judge_client, tutor_model, judge_model
        )
        judge_in, judge_out = judge_in + ji, judge_out + jo
        outcomes.append(outcome)
    return outcomes, judge_in, judge_out
