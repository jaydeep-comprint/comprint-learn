"""Auth dependencies, offline: a fake token verifier and a fake session hold the users."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import AnyUser, CurrentUser, Scope, get_current_user, require_admin
from app.core.auth import AuthUnavailable, Unauthenticated, get_token_verifier
from app.db.session import get_session
from app.main import create_app
from app.models import AppUser, Role, UserStatus

ORG = uuid.uuid4()


def _user(role: Role = Role.teacher, **kw: Any) -> AppUser:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org_id": ORG,
        "role": role,
        "is_admin": False,
        "display_name": "x",
        "status": UserStatus.active,
        "must_change_password": False,
    }
    values.update(kw)
    return AppUser(**values)


class FakeVerifier:
    unavailable = False

    async def verify(self, token: str) -> uuid.UUID:
        if self.unavailable:
            raise AuthUnavailable
        if not token.startswith("ok-"):
            raise Unauthenticated
        return uuid.UUID(token[3:])


class FakeSession:
    def __init__(self, users: list[AppUser]) -> None:
        self.users = {u.id: u for u in users}
        self.commits = 0

    async def get(self, _model: type, id_: uuid.UUID) -> AppUser | None:
        return self.users.get(id_)

    async def commit(self) -> None:
        self.commits += 1


def _app(users: list[AppUser], verifier: FakeVerifier | None = None) -> tuple[FastAPI, FakeSession]:
    app = create_app()
    session = FakeSession(users)

    async def fake_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_token_verifier] = lambda: verifier or FakeVerifier()

    from fastapi import Depends

    @app.get("/t/any")
    async def any_user(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    @app.get("/t/normal")
    async def normal(user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:  # noqa: B008
        return {"id": str(user.id)}

    @app.get("/t/admin")
    async def admin_only(user: CurrentUser = Depends(require_admin)) -> dict[str, str]:  # noqa: B008
        return {"id": str(user.id)}

    @app.get("/t/scope")
    async def scoped(scope: Scope) -> dict[str, str]:
        return {"org": str(scope.org_id)}

    return app, session


async def _get(app: FastAPI, path: str, user: AppUser | None, token: str | None = None) -> Any:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    elif user is not None:
        headers["Authorization"] = f"Bearer ok-{user.id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)


async def test_missing_header_is_401() -> None:
    app, _ = _app([])
    resp = await _get(app, "/t/normal", None)
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_invalid_token_is_401() -> None:
    app, _ = _app([])
    resp = await _get(app, "/t/normal", None, token="garbage")
    assert resp.status_code == 401


async def test_unknown_user_is_401() -> None:
    app, _ = _app([])
    resp = await _get(app, "/t/normal", _user())
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_deactivated_user_is_401() -> None:
    user = _user(status=UserStatus.deactivated)
    app, _ = _app([user])
    resp = await _get(app, "/t/any", user)
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_jwks_down_is_503_not_401() -> None:
    verifier = FakeVerifier()
    verifier.unavailable = True
    app, _ = _app([], verifier)
    resp = await _get(app, "/t/normal", _user())
    assert resp.status_code == 503
    assert resp.json()["code"] == "auth_unavailable"


async def test_must_change_password_blocks_normal_routes_only() -> None:
    student = _user(Role.student, username="a12", must_change_password=True)
    app, _ = _app([student])
    resp = await _get(app, "/t/normal", student)
    assert resp.status_code == 403
    assert resp.json()["code"] == "password_change_required"
    assert (await _get(app, "/t/any", student)).status_code == 200


async def test_invited_user_is_activated_on_first_request() -> None:
    teacher = _user(status=UserStatus.invited, email="t@x.in")
    app, session = _app([teacher])
    assert (await _get(app, "/t/any", teacher)).status_code == 200
    assert teacher.status == UserStatus.active
    assert session.commits == 1


async def test_student_on_staff_route_is_403() -> None:
    student = _user(Role.student, username="a12")
    app, _ = _app([student])
    resp = await _get(app, "/api/v1/classes", student)
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


async def test_non_admin_on_admin_route_is_403() -> None:
    teacher = _user(email="t@x.in")
    app, _ = _app([teacher])
    assert (await _get(app, "/t/admin", teacher)).status_code == 403
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/api/v1/teachers/invite",
            json={"email": "n@x.in", "display_name": "N"},
            headers={"Authorization": f"Bearer ok-{teacher.id}"},
        )
    assert resp.status_code == 403


async def test_admin_passes_admin_check_and_scope_uses_user_org() -> None:
    admin = _user(email="a@x.in", is_admin=True)
    app, _ = _app([admin])
    assert (await _get(app, "/t/admin", admin)).status_code == 200
    assert (await _get(app, "/t/scope", admin)).json() == {"org": str(ORG)}


@pytest.mark.parametrize("path", ["/api/v1/me", "/api/v1/classes", "/api/v1/students"])
async def test_api_routes_require_a_token(path: str) -> None:
    app, _ = _app([])
    assert (await _get(app, path, None)).status_code == 401
