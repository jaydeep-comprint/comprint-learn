"""One summary generation: prompt → model → guard → one retry (spec 011).

Shared by `services/teacher_ai.py` (between its two transactions, with no DB session open) and
the eval. Writes no rows and checks no caps.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai import teacher_guard, teacher_limits
from app.ai import teacher_prompts as prompts
from app.ai.teacher_client import TeacherAIUnavailable, TeacherCall, TeacherClient
from app.ai.teacher_facts import FactSet, render
from app.ai.teacher_schema import ModelOutput

Status = Literal["ok", "partial", "failed"]


@dataclass
class SummaryResult:
    status: Status
    output: ModelOutput | None
    dropped: list[tuple[str, str]] = field(default_factory=list)  # every call's drops
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    calls: int = 0


def build_request(fs: FactSet, model: str, retry_note: str | None = None) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": render(fs)},
    ]
    if retry_note is not None:
        messages.append({"role": "system", "content": retry_note})
    return {
        "model": model,
        "messages": messages,
        "max_tokens": teacher_limits.MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "temperature": teacher_limits.TEMPERATURE,
        "stream": False,
    }


def _add(result: SummaryResult, call: TeacherCall) -> None:
    result.calls += 1
    result.model = call.model or result.model
    result.input_tokens += call.input_tokens
    result.output_tokens += call.output_tokens
    result.cache_read_tokens += call.cache_read_tokens
    result.cache_write_tokens += call.cache_write_tokens
    result.latency_ms += call.latency_ms


def _unusable(call: TeacherCall) -> str | None:
    if call.stop_reason == "refusal":
        return "refused"
    if call.stop_reason == "length":
        return "cut off"
    if call.output is None:
        return "not valid JSON for the schema"
    return None


async def run_summary(fs: FactSet, client: TeacherClient, model: str) -> SummaryResult:
    """Raises `TeacherAIUnavailable` when the provider fails, or when the wall-clock cap expires
    before any call finished. If it expires after one, the result so far is returned (with its
    tokens): `partial` if an attempt left usable claims, else `failed`."""
    run = _Run(SummaryResult(status="failed", output=None))
    try:
        async with asyncio.timeout(teacher_limits.WALL_CLOCK_S):
            return await run.go(fs, client, model)
    except TimeoutError:
        if run.result.calls == 0:
            raise TeacherAIUnavailable("timeout") from None
        run.result.dropped.append(("reply", "timed out"))
        return run.finish()


@dataclass
class _Run:
    result: SummaryResult
    best: teacher_guard.GuardResult | None = None

    def finish(self) -> SummaryResult:
        if self.best is not None:
            self.result.status = "partial"
            self.result.output = self.best.kept
        return self.result

    async def go(self, fs: FactSet, client: TeacherClient, model: str) -> SummaryResult:
        result = self.result
        note: str | None = None
        for _attempt in range(2):
            call = await client.create(build_request(fs, model, note))
            _add(result, call)
            problem = _unusable(call)
            if problem is not None:
                dropped = [("reply", problem)]
            else:
                assert call.output is not None
                checked = teacher_guard.check(call.output, fs)
                dropped = checked.dropped
                if checked.status != "retry":
                    result.status = checked.status
                    result.output = checked.kept
                    result.dropped += dropped
                    return result
                if checked.kept.summary and (
                    self.best is None or checked.survivors > self.best.survivors
                ):
                    self.best = checked
            result.dropped += dropped
            note = prompts.retry_note(dropped)
        return self.finish()
