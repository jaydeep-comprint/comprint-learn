from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AnyUser, OrgScope, SessionDep
from app.schemas.tenancy import MeOut, OrgOut, PasswordIn
from app.services import tenancy
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

router = APIRouter(prefix="/me", tags=["me"])

# The only routes that accept users who still have a temp password (must_change_password).
AdminApi = Annotated[SupabaseAdmin, Depends(get_supabase_admin)]


@router.get("", response_model=MeOut)
async def get_me(user: AnyUser, session: SessionDep) -> MeOut:
    me, org = await tenancy.get_me(OrgScope(session, user))
    return MeOut(
        id=me.id,
        display_name=me.display_name,
        role=me.role,
        is_admin=me.is_admin,
        username=me.username,
        must_change_password=me.must_change_password,
        org=OrgOut(name=org.name, code=org.code),
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordIn, user: AnyUser, session: SessionDep, admin: AdminApi
) -> None:
    await tenancy.change_own_password(OrgScope(session, user), admin, body.new_password)
