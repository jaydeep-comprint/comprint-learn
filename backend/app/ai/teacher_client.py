"""The model client for teacher summaries (spec 011): DeepSeek on the tutor's `ChatClient` and key.

`TeacherClient.create(request)` takes a full `/chat/completions` body (built by `teacher_turn`) and
returns a `TeacherCall` with the parsed `ModelOutput` (None when the reply doesn't validate). Tests
override the `get_teacher_client` dependency with `tests/fakes.FakeTeacherClient`. A Claude client
would replace this module only.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from app.ai import teacher_limits
from app.ai.client import ChatClient, TutorUnavailable, complete_json, make_chat_client
from app.ai.teacher_schema import ModelOutput
from app.core.config import get_settings


class TeacherAIUnavailable(Exception):  # noqa: N818 - a state, not an error in our code
    """The provider couldn't be reached (timeout, rate limit, API or connection error)."""


@dataclass(frozen=True)
class TeacherCall:
    output: ModelOutput | None  # None: invalid JSON / shape, a refusal or a cut-off reply
    text: str
    stop_reason: str | None
    model: str
    input_tokens: int = 0  # uncached prompt tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0


class TeacherClient(Protocol):
    async def create(self, request: dict[str, Any]) -> TeacherCall: ...


def parse(text: str) -> ModelOutput | None:
    try:
        return ModelOutput.model_validate_json(text)
    except ValidationError:
        return None


class DeepSeekTeacherClient:
    def __init__(self, chat: ChatClient) -> None:
        self.chat = chat

    async def create(self, request: dict[str, Any]) -> TeacherCall:
        try:
            c = await complete_json(self.chat, request)
        except TutorUnavailable as exc:
            raise TeacherAIUnavailable(str(exc)) from None
        return TeacherCall(
            output=parse(c.text) if c.stop_reason == "stop" else None,
            text=c.text,
            stop_reason=c.stop_reason,
            model=c.model,
            input_tokens=c.input_tokens,
            output_tokens=c.output_tokens,
            cache_read_tokens=c.cache_read_tokens,
            latency_ms=c.latency_ms,
        )


_client: DeepSeekTeacherClient | None = None


def get_teacher_client() -> TeacherClient | None:
    """FastAPI dependency: the shared client, or None when teacher AI is off (or no key)."""
    global _client
    if not get_settings().teacher_ai_available:
        return None
    if _client is None:
        chat = make_chat_client(timeout=teacher_limits.TIMEOUT_S)
        if chat is None:
            return None
        _client = DeepSeekTeacherClient(chat)
    return _client
