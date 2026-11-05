"""The one place the tutor calls its model: DeepSeek's OpenAI-compatible API (spec 009).

`TutorClient.create(request)` takes a full `/chat/completions` request body (built by
`tutor_turn`) and returns a parsed `TutorCall`. Requests go over `httpx` (no provider SDK). The
real client is lazy and shared; tests override the `get_tutor_client` dependency with
`tests/fakes.FakeTutorClient`. Never log the API key.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.ai import limits
from app.core.config import get_settings

RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
MAX_RETRIES = 1
BLANK_RETRIES = 1  # blank JSON-mode content (see `DeepSeekTutorClient.create`)


class TutorUnavailable(Exception):  # noqa: N818 - a state, not an error in our code
    """The model call failed (timeout, rate limit, API or connection error)."""


@dataclass(frozen=True)
class TutorCall:
    category: str | None  # ok | needs_hint | off_topic | safety (None: bad output / refusal)
    reply: str | None
    stop_reason: str | None  # "stop", "length", "refusal" (a content filter), ...
    model: str
    input_tokens: int = 0  # uncached prompt tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0

    @property
    def refused(self) -> bool:
        return self.stop_reason == "refusal"

    @property
    def bad_output(self) -> bool:
        """Invalid JSON, a cut-off reply or an empty one: treated like a leak."""
        return not self.refused and (self.category is None or not (self.reply or "").strip())


class TutorClient(Protocol):
    async def create(self, request: dict[str, Any]) -> TutorCall: ...


_CATEGORIES = {"ok", "needs_hint", "off_topic", "safety"}


def parse_output(text: str) -> tuple[str | None, str | None]:
    """(category, reply) from the JSON output, or (None, None) if it isn't valid. JSON mode
    guarantees JSON, not our schema, so every field is checked here."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    category, reply = data.get("category"), data.get("reply")
    if category not in _CATEGORIES or not isinstance(reply, str):
        return None, None
    return category, reply


class ChatClient:
    """A minimal OpenAI-compatible chat client: one retry on timeouts, 429 and 5xx."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout: float = limits.TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """The raw response JSON. Raises `TutorUnavailable` on any failure."""
        for attempt in range(MAX_RETRIES + 1):
            last = attempt == MAX_RETRIES
            try:
                response = await self._http.post("/chat/completions", json=request)
            except httpx.TimeoutException as exc:
                if last:
                    raise TutorUnavailable("timeout") from exc
                continue
            except httpx.TransportError as exc:
                if last:
                    raise TutorUnavailable("connection") from exc
                continue
            if response.status_code in RETRY_STATUSES and not last:
                continue
            if response.status_code != 200:
                raise TutorUnavailable(f"status {response.status_code}")
            try:
                data: dict[str, Any] = response.json()
            except ValueError as exc:
                raise TutorUnavailable("invalid response") from exc
            return data
        raise TutorUnavailable("unreachable")  # pragma: no cover


class DeepSeekTutorClient:
    def __init__(self, chat: ChatClient) -> None:
        self.chat = chat

    async def create(self, request: dict[str, Any]) -> TutorCall:
        started = time.monotonic()
        for _ in range(BLANK_RETRIES + 1):
            data = await self.chat.complete(request)
            try:
                choice = data["choices"][0]
                text = choice["message"].get("content") or ""
                finish = choice.get("finish_reason")
            except (KeyError, IndexError, TypeError, AttributeError) as exc:
                raise TutorUnavailable("unexpected response shape") from exc
            # DeepSeek's JSON mode sometimes returns blank content with finish "stop": transient,
            # so ask again here rather than spend the guard's one retry on it.
            if text.strip() or finish != "stop":
                break
        latency = int((time.monotonic() - started) * 1000)
        if finish == "insufficient_system_resource":
            raise TutorUnavailable("provider overloaded")
        stop = "refusal" if finish == "content_filter" else finish
        category, reply = (None, None)
        if stop == "stop":
            category, reply = parse_output(text)
        usage = data.get("usage") or {}
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        prompt = int(usage.get("prompt_tokens") or 0)
        return TutorCall(
            category=category,
            reply=reply,
            stop_reason=stop,
            model=str(data.get("model") or request.get("model") or ""),
            input_tokens=max(0, prompt - hit),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_read_tokens=hit,
            latency_ms=latency,
        )


_client: DeepSeekTutorClient | None = None


def make_chat_client(timeout: float = limits.TIMEOUT_S) -> ChatClient | None:
    settings = get_settings()
    if settings.deepseek_api_key is None:
        return None
    return ChatClient(
        settings.deepseek_api_key.get_secret_value(), settings.tutor_base_url, timeout=timeout
    )


def get_tutor_client() -> TutorClient | None:
    """FastAPI dependency: the shared client, or None when the tutor is off (no key)."""
    global _client
    if _client is None:
        chat = make_chat_client()
        if chat is None:
            return None
        _client = DeepSeekTutorClient(chat)
    return _client
