"""One tutor turn: prompt → model → guard → one retry → canned fallback (spec 009).

`run_turn` is shared by `services/tutor.py` (between its two transactions, with no DB session
open) and the eval. It writes no rows and checks no caps. Each call is the static system prompt
and a single user turn: the context block (a stable prefix the provider caches), then the thread
so far as a `<transcript>` (data, not replayed assistant turns) and the current request. The
guard-retry note is a trailing system message, so the prefix stays the same.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai import guard, limits, safety
from app.ai import tutor_prompts as prompts
from app.ai.client import TutorCall, TutorClient
from app.ai.context import PrereqInfo, TutorContext

REPLY_NOW = "Reply with the JSON object now."
TEMPERATURE = 0.3  # steady, on-rung replies; not 0, so a guard retry can differ

Status = Literal["ok", "guarded", "fallback", "safety", "refused"]


@dataclass(frozen=True)
class TranscriptLine:
    role: Literal["student", "tutor"]
    kind: Literal["hint", "chat"]
    rung: int | None
    text: str | None


@dataclass(frozen=True)
class TurnRequest:
    kind: Literal["hint", "chat"]
    rung: int | None = None
    text: str | None = None  # chat: already scrubbed of personal data
    draft: str | None = None


@dataclass
class TurnResult:
    text: str
    status: Status
    category: str | None
    flagged: bool = False
    link: PrereqInfo | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    calls: int = 0
    leaks: list[guard.Leak] = field(default_factory=list)  # what the guard caught (last call)
    caught: list[guard.Leak] = field(default_factory=list)  # every call's catches (eval report)


def _esc(text: str) -> str:
    return text.replace("<", "&lt;")


def render_transcript(lines: list[TranscriptLine]) -> str:
    out = []
    for line in lines:
        if line.role == "student":
            if line.kind == "hint":
                out.append(f"Student pressed Hint ({line.rung}).")
            else:
                out.append(f"Student: {_esc(line.text or '')}")
        else:
            label = f"Tutor (hint {line.rung})" if line.kind == "hint" else "Tutor"
            out.append(f"{label}: {line.text or ''}")
    return "<transcript>\n" + ("\n".join(out) if out else "(empty)") + "\n</transcript>"


def render_request(req: TurnRequest) -> str:
    if req.kind == "hint":
        assert req.rung is not None
        head = f"HINT REQUEST: rung {req.rung} ({prompts.RUNG_NAMES[req.rung]})."
    else:
        head = f"<student_message>\n{_esc(req.text or '')}\n</student_message>"
    if req.draft:
        head += f"\n<student_draft>\n{_esc(req.draft)}\n</student_draft>"
    # Without a closing instruction after the student's text, DeepSeek's JSON mode often returns
    # blank content (measured: 0/4 good vs 4/4 with this line).
    return head + "\n\n" + REPLY_NOW


def build_request(
    ctx: TutorContext,
    transcript: list[TranscriptLine],
    req: TurnRequest,
    model: str,
    retry_note: str | None = None,
) -> dict[str, Any]:
    """A `/chat/completions` body. The system prompt and the context block come first and stay
    byte-identical across a thread's calls, so the provider's prefix cache can reuse them."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {
            "role": "user",
            "content": ctx.text
            + "\n\n"
            + render_transcript(transcript)
            + "\n\n"
            + render_request(req),
        },
    ]
    if retry_note is not None:
        messages.append({"role": "system", "content": retry_note})
    return {
        "model": model,
        "messages": messages,
        "max_tokens": limits.MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "temperature": TEMPERATURE,
        "stream": False,
    }


def canned(ctx: TutorContext, req: TurnRequest) -> tuple[str, PrereqInfo | None]:
    if req.kind == "chat":
        return prompts.FALLBACK_CHAT, None
    if req.rung == 1:
        return prompts.FALLBACK_RUNG_1.format(kp_title=ctx.kp_title), None
    if req.rung == 2:
        if ctx.prereq is None:
            return prompts.FALLBACK_RUNG_2_NO_PREREQ.format(concept_title=ctx.concept_title), None
        return prompts.FALLBACK_RUNG_2.format(prereq_title=ctx.prereq.title), ctx.prereq
    return prompts.FALLBACK_RUNG_3, None


def _leaks(ctx: TutorContext, call: TutorCall, req: TurnRequest) -> list[guard.Leak]:
    if call.bad_output:
        return [guard.Leak("length", "format")]
    if call.category in ("needs_hint", "off_topic", "safety") and req.kind == "chat":
        return []  # replaced by a fixed reply
    limit = limits.HINT_WORDS if req.kind == "hint" else limits.CHAT_WORDS
    return guard.check(
        call.reply or "",
        ctx.facts,
        mode=ctx.mode,
        word_limit=limit,
        draft=req.draft,
        solution_shown=ctx.solution_shown,
    )


def _add_usage(result: TurnResult, call: TutorCall) -> None:
    result.model = call.model
    result.input_tokens += call.input_tokens
    result.output_tokens += call.output_tokens
    result.cache_read_tokens += call.cache_read_tokens
    result.cache_write_tokens += call.cache_write_tokens
    result.latency_ms += call.latency_ms
    result.calls += 1


async def run_turn(
    ctx: TutorContext,
    transcript: list[TranscriptLine],
    req: TurnRequest,
    client: TutorClient,
    model: str,
) -> TurnResult:
    """Raises `TutorUnavailable` if a model call fails (nothing is charged then)."""
    if req.kind == "chat" and safety.is_distress(req.text or ""):
        return TurnResult(prompts.SAFETY_REPLY, "safety", "safety", flagged=True)
    result = TurnResult("", "ok", None)
    note: str | None = None
    for attempt in range(2):
        call = await client.create(build_request(ctx, transcript, req, model, note))
        _add_usage(result, call)
        if call.refused:
            result.text, result.status, result.category = prompts.REFUSED_REPLY, "refused", None
            return result
        if call.category == "safety":
            result.text, result.status, result.category = prompts.SAFETY_REPLY, "safety", "safety"
            result.flagged = True
            return result
        leaks = _leaks(ctx, call, req)
        result.leaks = leaks
        result.caught += leaks
        if not leaks:
            result.category = call.category
            result.status = "guarded" if attempt else "ok"
            if req.kind == "chat" and call.category == "needs_hint":
                result.text = prompts.NEEDS_HINT_REPLY
            elif req.kind == "chat" and call.category == "off_topic":
                result.text = prompts.OFF_TOPIC_REPLY
            else:
                result.text = (call.reply or "").strip()
            if req.kind == "hint":
                result.category = "ok"
                if req.rung == 2:
                    result.link = ctx.prereq
            return result
        kinds = ["format" if leak.detail == "format" else leak.kind for leak in leaks]
        note = prompts.retry_note(kinds)
    result.text, result.link = canned(ctx, req)
    result.status, result.category = "fallback", "ok" if req.kind == "hint" else None
    return result
