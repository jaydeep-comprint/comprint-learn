import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AdminScope, StaffScope
from app.schemas.tenancy import TeacherInviteIn, TeacherOut, TeacherPatch
from app.services import tenancy
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

router = APIRouter(prefix="/teachers", tags=["teachers"])

AdminApi = Annotated[SupabaseAdmin, Depends(get_supabase_admin)]


@router.get("", response_model=list[TeacherOut])
async def list_teachers(scope: StaffScope) -> list[TeacherOut]:
    return [TeacherOut.model_validate(t) for t in await tenancy.list_teachers(scope)]


@router.post("/invite", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
async def invite_teacher(body: TeacherInviteIn, scope: AdminScope, admin: AdminApi) -> TeacherOut:
    user = await tenancy.invite_teacher(scope, admin, str(body.email), body.display_name)
    return TeacherOut.model_validate(user)


@router.post("/{user_id}/resend-invite", status_code=status.HTTP_204_NO_CONTENT)
async def resend_invite(user_id: uuid.UUID, scope: AdminScope, admin: AdminApi) -> None:
    await tenancy.resend_invite(scope, admin, user_id)


@router.patch("/{user_id}", response_model=TeacherOut)
async def patch_teacher(
    user_id: uuid.UUID, body: TeacherPatch, scope: AdminScope, admin: AdminApi
) -> TeacherOut:
    user = await tenancy.patch_teacher(
        scope, admin, user_id, is_admin=body.is_admin, status=body.status
    )
    return TeacherOut.model_validate(user)
