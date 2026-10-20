import json
import uuid

import httpx
import pytest

from app.services.supabase_admin import BAN_FOREVER, HttpSupabaseAdmin, SupabaseAdminError

BASE = "https://test-project.supabase.co"
USER_ID = uuid.uuid4()


def _admin(handler: httpx.MockTransport) -> HttpSupabaseAdmin:
    return HttpSupabaseAdmin(BASE, "service-key", transport=handler)


async def test_invite_sends_service_key_and_redirect() -> None:
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": str(USER_ID), "email": "t@x.in"})

    uid = await _admin(httpx.MockTransport(handle)).invite("t@x.in", "http://app/accept-invite")
    assert uid == USER_ID
    req = seen[0]
    assert req.url.path == "/auth/v1/invite"
    assert req.url.params["redirect_to"] == "http://app/accept-invite"
    assert req.headers["apikey"] == "service-key"
    assert req.headers["authorization"] == "Bearer service-key"
    assert json.loads(req.content) == {"email": "t@x.in"}


async def test_create_user_is_confirmed() -> None:
    bodies: list[object] = []

    def handle(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"id": str(USER_ID)})

    await _admin(httpx.MockTransport(handle)).create_user("a@b.students.invalid", "pw-pw-12")
    assert bodies == [
        {"email": "a@b.students.invalid", "password": "pw-pw-12", "email_confirm": True}
    ]


@pytest.mark.parametrize(("banned", "duration"), [(True, BAN_FOREVER), (False, "none")])
async def test_ban_and_unban(banned: bool, duration: str) -> None:
    bodies: list[object] = []

    def handle(req: httpx.Request) -> httpx.Response:
        assert req.method == "PUT" and req.url.path == f"/auth/v1/admin/users/{USER_ID}"
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"id": str(USER_ID)})

    await _admin(httpx.MockTransport(handle)).set_banned(USER_ID, banned)
    assert bodies == [{"ban_duration": duration}]


async def test_http_error_raises_without_leaking_body(caplog: pytest.LogCaptureFixture) -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"msg": "boom for secret@x.in"})

    with pytest.raises(SupabaseAdminError) as exc:
        await _admin(httpx.MockTransport(handle)).update_password(USER_ID, "tiger-maple-42")
    assert exc.value.status == 500
    assert "secret@x.in" not in caplog.text and "tiger-maple-42" not in caplog.text


async def test_network_error_raises() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(SupabaseAdminError):
        await _admin(httpx.MockTransport(handle)).delete_user(USER_ID)


async def test_missing_id_in_response_raises() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(SupabaseAdminError):
        await _admin(httpx.MockTransport(handle)).create_user("a@b.c", "x")
