"""The DeepSeek chat client (spec 009), offline with a mock transport: parsing, refusal and
cut-off mapping, cache usage, one retry, and failures → `TutorUnavailable`."""

import json
from typing import Any

import httpx
import pytest

from app.ai.client import ChatClient, DeepSeekTutorClient, TutorUnavailable


def body(content: str, finish: str = "stop", **usage: int) -> dict[str, Any]:
    return {
        "model": "deepseek-chat",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 40, **usage},
    }


def client(*responses: httpx.Response | Exception) -> tuple[DeepSeekTutorClient, list[Any]]:
    queue = list(responses)
    seen: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    chat = ChatClient("sk-test", "https://api.example", transport=httpx.MockTransport(handler))
    return DeepSeekTutorClient(chat), seen


async def test_parses_reply_and_usage() -> None:
    reply = json.dumps({"category": "ok", "reply": "Look at the worked example."})
    c, seen = client(httpx.Response(200, json=body(reply, prompt_cache_hit_tokens=800)))
    call = await c.create({"model": "deepseek-chat", "messages": []})
    assert (call.category, call.reply, call.stop_reason) == (
        "ok",
        "Look at the worked example.",
        "stop",
    )
    assert (call.input_tokens, call.cache_read_tokens, call.output_tokens) == (200, 800, 40)
    assert seen[0].url == "https://api.example/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer sk-test"


@pytest.mark.parametrize(
    ("content", "finish", "refused", "bad"),
    [
        ("{}", "stop", False, True),  # valid JSON, wrong shape
        ("not json", "stop", False, True),
        ('{"category": "ok", "reply": "cut off', "length", False, True),
        ("", "content_filter", True, False),
    ],
)
async def test_bad_output_and_refusal(content: str, finish: str, refused: bool, bad: bool) -> None:
    c, _ = client(httpx.Response(200, json=body(content, finish)))
    call = await c.create({})
    assert (call.refused, call.bad_output) == (refused, bad)


async def test_retries_once_then_succeeds() -> None:
    ok = json.dumps({"category": "ok", "reply": "hi"})
    c, seen = client(httpx.Response(503), httpx.Response(200, json=body(ok)))
    assert (await c.create({})).reply == "hi"
    assert len(seen) == 2


@pytest.mark.parametrize(
    "responses",
    [
        (httpx.Response(429), httpx.Response(429)),
        (httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")),
        (httpx.ConnectError("down"), httpx.ConnectError("down")),
        (httpx.Response(401),),  # not retried
        (httpx.Response(200, json={"oops": True}),),
        (httpx.Response(200, json=body("", "insufficient_system_resource")),),
    ],
)
async def test_failures_are_unavailable(responses: tuple[Any, ...]) -> None:
    c, _ = client(*responses)
    with pytest.raises(TutorUnavailable):
        await c.create({})


async def test_blank_content_is_asked_again() -> None:
    ok = json.dumps({"category": "ok", "reply": "hi"})
    c, seen = client(httpx.Response(200, json=body("   ")), httpx.Response(200, json=body(ok)))
    assert (await c.create({})).reply == "hi"
    assert len(seen) == 2
    twice, _ = client(httpx.Response(200, json=body(" ")), httpx.Response(200, json=body(" ")))
    assert (await twice.create({})).bad_output  # then the guard's retry / fallback handles it
