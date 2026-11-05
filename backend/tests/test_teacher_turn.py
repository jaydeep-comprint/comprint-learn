"""One summary generation (spec 011): request shape, guard retry, better of two, failures."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.ai import teacher_limits, teacher_turn
from app.ai.client import ChatClient
from app.ai.teacher_client import DeepSeekTeacherClient, TeacherAIUnavailable, TeacherCall
from app.ai.teacher_facts import Fact, FactSet, Resource
from tests.fakes import FakeTeacherClient

FS = FactSet(
    kind="class",
    window="7d",
    facts=[
        Fact("F1", "class", "25 students in scope.", [], {}),
        Fact("F2", "weak_concept", "Concept 'Lin': 6 of 14 KP tries failed (43%).", [], {}),
    ],
    resources=[Resource("R1", "lesson", "Lin", "maths/lin", "Lin")],
    pseudonyms={},
)
GOOD = {"text": "Lin is weakest: 6 of 14 tries failed.", "facts": ["F2"]}
BAD = {"text": "9 students failed Lin.", "facts": ["F2"]}


def run(client: Any) -> teacher_turn.SummaryResult:
    return asyncio.run(teacher_turn.run_summary(FS, client, "deepseek-v4-pro"))


def test_request_shape() -> None:
    fake = FakeTeacherClient({"summary": [GOOD, GOOD]})
    result = run(fake)
    assert result.status == "ok" and result.calls == 1
    body = fake.requests[0]
    assert body["model"] == "deepseek-v4-pro"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == teacher_limits.MAX_TOKENS
    assert body["temperature"] == teacher_limits.TEMPERATURE
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "JSON" in body["messages"][0]["content"]
    assert body["messages"][1]["content"].endswith("Reply with the JSON object now.")
    assert result.input_tokens == 1200 and result.cache_read_tokens == 800


def test_bad_reply_retries_once_with_a_trailing_system_note() -> None:
    fake = FakeTeacherClient({"summary": [BAD, BAD]}, {"summary": [GOOD, GOOD]})
    result = run(fake)
    assert result.status == "ok" and result.calls == 2
    second = fake.requests[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "system"]
    assert "number 9 not in its facts" in second[2]["content"]
    assert second[:2] == fake.requests[0]["messages"]  # the cached prefix stays the same


def test_keeps_the_better_of_two_as_partial() -> None:
    fake = FakeTeacherClient(
        {"summary": [GOOD, BAD, BAD]}, {"summary": [GOOD, GOOD, BAD, BAD, BAD]}
    )
    result = run(fake)
    assert result.status == "partial"
    assert result.output is not None and len(result.output.summary) == 2


def test_fails_after_two_unusable_replies() -> None:
    refused = TeacherCall(output=None, text="", stop_reason="refusal", model="m")
    result = run(FakeTeacherClient(refused, "not json"))
    assert result.status == "failed" and result.output is None and result.calls == 2
    assert ("reply", "refused") in result.dropped


def test_cut_off_counts_as_a_failed_attempt() -> None:
    cut = TeacherCall(output=None, text='{"summ', stop_reason="length", model="m")
    result = run(FakeTeacherClient(cut, {"summary": [GOOD]}))
    assert result.status == "ok" and result.calls == 2


def test_provider_error_propagates() -> None:
    with pytest.raises(TeacherAIUnavailable):
        run(FakeTeacherClient(TeacherAIUnavailable("timeout")))


def test_wall_clock_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(teacher_limits, "WALL_CLOCK_S", 0.01)
    fake = FakeTeacherClient()
    fake.gate = asyncio.Event()
    with pytest.raises(TeacherAIUnavailable):
        run(fake)


def _transport(content: str, finish: str = "stop", status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "model": "deepseek-v4-pro-2026",
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": 3000,
                    "prompt_cache_hit_tokens": 2000,
                    "completion_tokens": 900,
                },
            },
        )

    return httpx.MockTransport(handler)


def test_deepseek_client_parses_and_logs_the_response_model() -> None:
    chat = ChatClient("k", "https://x", transport=_transport(json.dumps({"summary": [GOOD]})))
    call = asyncio.run(DeepSeekTeacherClient(chat).create({"model": "deepseek-v4-pro"}))
    assert call.output is not None and call.output.summary[0].facts == ["F2"]
    assert call.model == "deepseek-v4-pro-2026"
    assert (call.input_tokens, call.cache_read_tokens, call.output_tokens) == (1000, 2000, 900)


def test_deepseek_client_maps_failures() -> None:
    chat = ChatClient("k", "https://x", transport=_transport("{}", status=500))
    with pytest.raises(TeacherAIUnavailable):
        asyncio.run(DeepSeekTeacherClient(chat).create({}))
    chat = ChatClient("k", "https://x", transport=_transport("", "insufficient_system_resource"))
    with pytest.raises(TeacherAIUnavailable):
        asyncio.run(DeepSeekTeacherClient(chat).create({}))
    chat = ChatClient("k", "https://x", transport=_transport("{}", "content_filter"))
    call = asyncio.run(DeepSeekTeacherClient(chat).create({}))
    assert call.stop_reason == "refusal" and call.output is None
