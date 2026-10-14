"""Test doubles shared by offline and DB tests."""

import uuid

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
        self.users[user_id]["password"] = password

    async def set_banned(self, user_id: uuid.UUID, banned: bool) -> None:
        self._maybe_fail("set_banned")
        self.users[user_id]["banned"] = banned

    async def delete_user(self, user_id: uuid.UUID) -> None:
        self._maybe_fail("delete_user")
        self.deleted.append(user_id)
        self.users.pop(user_id, None)
