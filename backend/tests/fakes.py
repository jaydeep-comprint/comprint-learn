"""Test doubles shared by offline and DB tests."""

import asyncio
import uuid
from typing import Any

from app.ai.client import TutorCall
from app.services.supabase_admin import SupabaseAdminError


class FakeSupabaseAdmin:
    """In-memory Supabase admin API. `fail_on` makes an op fail (after `fail_after` calls)."""

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, dict[str, object]] = {}
        self.invites: list[str] = []
        self.deleted: list[uuid.UUID] = []
        self.calls: list[str] = []
        self.fail_on: str | None = None
        self.fail_after = 0  # successful calls of `fail_on` before it starts failing

    def _maybe_fail(self, op: str) -> None:
        self.calls.append(op)
        if self.fail_on == op:
            if self.fail_after <= 0:
                raise SupabaseAdminError(op, 500)
            self.fail_after -= 1

    def _user(self, user_id: uuid.UUID) -> dict[str, object]:
        """Users seeded straight into the DB exist in "Supabase" too."""
        return self.users.setdefault(user_id, {"email": None, "password": None, "banned": False})

    def _by_email(self, email: str) -> uuid.UUID | None:
        return next((i for i, u in self.users.items() if u["email"] == email), None)

    async def invite(self, email: str, redirect_to: str) -> uuid.UUID:
        self._maybe_fail("invite")
        self.invites.append(email)
        existing = self._by_email(email)
        if existing:
            return existing
        uid = uuid.uuid4()
        self.users[uid] = {"email": email, "password": None, "banned": False}
        return uid

    async def create_user(self, email: str, password: str) -> uuid.UUID:
        self._maybe_fail("create_user")
        if self._by_email(email):
            raise SupabaseAdminError("create_user", 422)
        uid = uuid.uuid4()
        self.users[uid] = {"email": email, "password": password, "banned": False}
        return uid

    async def update_password(self, user_id: uuid.UUID, password: str) -> None:
        self._maybe_fail("update_password")
        self._user(user_id)["password"] = password

    async def set_banned(self, user_id: uuid.UUID, banned: bool) -> None:
        self._maybe_fail("set_banned")
        self._user(user_id)["banned"] = banned

    async def delete_user(self, user_id: uuid.UUID) -> None:
        self._maybe_fail("delete_user")
        self.deleted.append(user_id)
        self.users.pop(user_id, None)


class FakeTutorClient:
    """Scripted tutor model (spec 009). `replies` is a queue: each entry is a `TutorCall`, a
    `(category, reply)` pair, or an exception to raise. Every request is recorded (the full
    `/chat/completions` body) so tests can assert on what the model would see."""

    def __init__(self, *replies: object) -> None:
        self.replies: list[object] = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.gate: asyncio.Event | None = None  # set to hold calls until released
        self.started = asyncio.Event()

    def queue(self, *replies: object) -> None:
        self.replies += list(replies)

    async def create(self, request: dict[str, Any]) -> TutorCall:
        self.requests.append(request)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        reply = self.replies.pop(0) if self.replies else ("ok", "Look at the worked example.")
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, TutorCall):
            return reply
        assert isinstance(reply, tuple)
        category, text = str(reply[0]), str(reply[1])
        return TutorCall(
            category=category,
            reply=text,
            stop_reason="end_turn",
            model="fake-haiku",
            input_tokens=100,
            output_tokens=20,
        )

    def prompt_text(self, index: int = -1) -> str:
        """Everything the model saw in request `index`, as one string."""
        return "\n".join(str(m["content"]) for m in self.requests[index]["messages"])
