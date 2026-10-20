import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import StaffScope
from app.core.errors import forbidden
from app.schemas.tenancy import StudentOut, StudentPatch, TempPasswordOut
from app.services import tenancy
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

router = APIRouter(prefix="/students", tags=["students"])

AdminApi = Annotated[SupabaseAdmin, Depends(get_supabase_admin)]


@router.get("", response_model=list[StudentOut])
async def list_students(
    scope: StaffScope,
    q: Annotated[str | None, Query(max_length=80)] = None,
    class_id: uuid.UUID | None = None,
) -> list[StudentOut]:
    return await tenancy.list_students(scope, q, class_id)


@router.patch("/{student_id}", response_model=StudentOut)
async def patch_student(
    student_id: uuid.UUID, body: StudentPatch, scope: StaffScope, admin: AdminApi
) -> StudentOut:
    if body.status is not None and not scope.user.is_admin:
        raise forbidden()
    return await tenancy.patch_student(
        scope, admin, student_id, display_name=body.display_name, status=body.status
    )


@router.post("/{student_id}/reset-password", response_model=TempPasswordOut)
async def reset_password(
    student_id: uuid.UUID, scope: StaffScope, admin: AdminApi
) -> TempPasswordOut:
    return await tenancy.reset_student_password(scope, admin, student_id)
