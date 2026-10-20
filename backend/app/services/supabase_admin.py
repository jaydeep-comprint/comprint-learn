"""Supabase Auth admin API (service-role key), behind a Protocol so tests inject a fake.

Request/response bodies are never logged (they hold emails and passwords); failures log the
operation and status code only.

Signing a user out of other sessions: Supabase has no admin "log out user X" endpoint, but an admin
password update (`update_password`) revokes all of the user's sessions, which is what a reset needs.
Deactivation bans the user (refresh fails) and our API rejects them on every request regardless.
"""

import logging
import uuid
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 10.0
# ~100 years: Supabase's way to ban indefinitely. "none" lifts the ban.
BAN_FOREVER = "876000h"


class SupabaseAdminError(Exception):
    """The admin API failed or was unreachable. Callers turn this into a friendly 502."""

    def __init__(self, operation: str, status: int | None = None) -> None:
        super().__init__(f"Supabase admin {operation} failed (status {status})")
        self.operation = operation
        self.status = status


class SupabaseAdmin(Protocol):
    async def invite(self, email: str, redirect_to: str) -> uuid.UUID:
        """Send (or re-send) an invite email; returns the auth user id."""
        ...

    async def create_user(self, email: str, password: str) -> uuid.UUID:
        """Create a confirmed user (no email sent); returns the auth user id."""
        ...

    async def update_password(self, user_id: uuid.UUID, password: str) -> None:
        """Set a new password. Also revokes all of the user's sessions."""
        ...

    async def set_banned(self, user_id: uuid.UUID, banned: bool) -> None: ...

    async def delete_user(self, user_id: uuid.UUID) -> None: ...


class HttpSupabaseAdmin:
    def __init__(
        self,
        base_url: str,
        service_role_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = f"{base_url}/auth/v1"
        self._transport = transport
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        }

    async def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_S, headers=self._headers, transport=self._transport
            ) as client:
                resp = await client.request(method, self._base + path, json=json, params=params)
        except httpx.HTTPError as exc:
            logger.warning("Supabase admin %s: %s", operation, type(exc).__name__)
            raise SupabaseAdminError(operation) from exc
        if resp.status_code >= 400:
            logger.warning("Supabase admin %s: HTTP %s", operation, resp.status_code)
            raise SupabaseAdminError(operation, resp.status_code)
        if not resp.content:
            return {}
        data: dict[str, Any] = resp.json()
        return data

    @staticmethod
    def _user_id(operation: str, data: dict[str, Any]) -> uuid.UUID:
        try:
            return uuid.UUID(str(data["id"]))
        except (KeyError, ValueError) as exc:
            raise SupabaseAdminError(operation) from exc

    async def invite(self, email: str, redirect_to: str) -> uuid.UUID:
        data = await self._request(
            "invite", "POST", "/invite", json={"email": email}, params={"redirect_to": redirect_to}
        )
        return self._user_id("invite", data)

    async def create_user(self, email: str, password: str) -> uuid.UUID:
        data = await self._request(
            "create_user",
            "POST",
            "/admin/users",
            json={"email": email, "password": password, "email_confirm": True},
        )
        return self._user_id("create_user", data)

    async def update_password(self, user_id: uuid.UUID, password: str) -> None:
        await self._request(
            "update_password", "PUT", f"/admin/users/{user_id}", json={"password": password}
        )

    async def set_banned(self, user_id: uuid.UUID, banned: bool) -> None:
        duration = BAN_FOREVER if banned else "none"
        await self._request(
            "set_banned", "PUT", f"/admin/users/{user_id}", json={"ban_duration": duration}
        )

    async def delete_user(self, user_id: uuid.UUID) -> None:
        await self._request("delete_user", "DELETE", f"/admin/users/{user_id}")


def get_supabase_admin() -> SupabaseAdmin:
    """FastAPI dependency (tests override it with a fake)."""
    settings = get_settings()
    return HttpSupabaseAdmin(settings.require_supabase_url(), settings.require_service_role_key())
