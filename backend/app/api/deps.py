"""Auth and org scoping: the one choke point every tenant-owned query goes through.

- `get_current_user`: verified bearer token → `app_user` row → `CurrentUser`. Rejects unknown and
  deactivated users (401) and users who must change their password (403).
- `require_staff` / `require_admin` / `require_student`: role checks (403).
- `OrgScope` (`Scope`, `StaffScope`, `AdminScope`): builds every tenant query with `org_id` set, and
  returns 404 for ids in other schools.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar, cast

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUnavailable, TokenVerifier, Unauthenticated, get_token_verifier
from app.core.errors import ApiProblem, forbidden, not_found, unauthenticated
from app.db.session import get_session
from app.models import AppUser, Role, TenantMixin, UserStatus

T = TypeVar("T", bound=TenantMixin)

# Supabase (token `iat`) and Postgres (`now()`) clocks can differ a little; a fresh sign-in right
# after a password change must not be rejected.
TOKEN_CLOCK_SKEW_S = 5

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    org_id: uuid.UUID
    role: Role
    is_admin: bool
    must_change_password: bool

    @property
    def is_staff(self) -> bool:
        return self.role == Role.teacher


async def get_current_user_allow_password_change(
    session: SessionDep,
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Like `get_current_user` but lets through users with a temp password.

    Only `GET /me` and `POST /me/password` may use this (tests/test_route_scoping.py enforces it).
    """
    if creds is None:
        raise unauthenticated()
    try:
        token = await verifier.verify(creds.credentials)
    except Unauthenticated as exc:
        raise unauthenticated() from exc
    except AuthUnavailable as exc:
        raise ApiProblem(503, "auth_unavailable", "Sign-in is unavailable; try again.") from exc

    # Identity lookup by the verified token's `sub` (the only by-id query outside OrgScope).
    user = await session.get(AppUser, token.user_id)
    if user is None or user.status == UserStatus.deactivated:
        raise unauthenticated()
    if user.sessions_valid_after is not None and token.issued_at < (
        user.sessions_valid_after.timestamp() - TOKEN_CLOCK_SKEW_S
    ):
        # Issued before a password reset/change or deactivation: that session is over.
        raise unauthenticated()
    if user.status == UserStatus.invited:
        # First authenticated request after accepting the invite.
        user.status = UserStatus.active
        await session.commit()
    return CurrentUser(
        id=user.id,
        org_id=user.org_id,
        role=user.role,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
    )


AnyUser = Annotated[CurrentUser, Depends(get_current_user_allow_password_change)]


async def get_current_user(user: AnyUser) -> CurrentUser:
    if user.must_change_password:
        raise ApiProblem(403, "password_change_required", "Choose a new password first.")
    return user


async def require_staff(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if not user.is_staff:
        raise forbidden()
    return user


async def require_admin(user: Annotated[CurrentUser, Depends(require_staff)]) -> CurrentUser:
    if not user.is_admin:
        raise forbidden()
    return user


async def require_student(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    if user.role != Role.student:
        raise forbidden()
    return user


class OrgScope:
    """Tenant-scoped query helper. Services take this, never a raw session + id."""

    def __init__(self, session: AsyncSession, user: CurrentUser) -> None:
        self.session = session
        self.user = user
        self.org_id = user.org_id

    @classmethod
    def system(cls, session: AsyncSession, org_id: uuid.UUID) -> "OrgScope":
        """A scope with no signed-in user, for the operator CLI (`app org create`) only."""
        actor = CurrentUser(
            id=uuid.UUID(int=0),
            org_id=org_id,
            role=Role.teacher,
            is_admin=True,
            must_change_password=False,
        )
        return cls(session, actor)

    def select(self, model: type[T]) -> Select[T]:
        return select(model).where(cast(Any, model).org_id == self.org_id)

    async def get(self, model: type[T], id_: uuid.UUID, *, for_update: bool = False) -> T:
        """The row with this id in the caller's school, else 404 (never 403)."""
        stmt = self.select(model).where(cast(Any, model).id == id_)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise not_found()
        return row

    def new(self, model: type[T], **values: Any) -> T:
        """A new row in the caller's school, added to the session."""
        if "org_id" in values:
            raise ValueError("org_id is set by OrgScope")
        row: T = cast(Any, model)(org_id=self.org_id, **values)
        self.session.add(row)
        return row


async def get_org_scope(
    session: SessionDep, user: Annotated[CurrentUser, Depends(get_current_user)]
) -> OrgScope:
    return OrgScope(session, user)


async def get_staff_scope(
    session: SessionDep, user: Annotated[CurrentUser, Depends(require_staff)]
) -> OrgScope:
    return OrgScope(session, user)


async def get_admin_scope(
    session: SessionDep, user: Annotated[CurrentUser, Depends(require_admin)]
) -> OrgScope:
    return OrgScope(session, user)


Scope = Annotated[OrgScope, Depends(get_org_scope)]
StaffScope = Annotated[OrgScope, Depends(get_staff_scope)]
AdminScope = Annotated[OrgScope, Depends(get_admin_scope)]
