import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.deps import AdminScope, StaffScope
from app.core.errors import forbidden
from app.models import AuditAction
from app.schemas.privacy import ConsentIn, EraseIn
from app.schemas.tenancy import StudentOut, StudentPatch, TempPasswordOut
from app.services import audit, consent, erasure, export, kp_flow, tenancy
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


@router.post("/consent", response_model=list[StudentOut])
async def set_consent(body: ConsentIn, scope: StaffScope) -> list[StudentOut]:
    """Spec 014: record or withdraw AI-tutor consent for 1-200 students (any teacher)."""
    return await consent.apply(scope, body.student_ids, body.action)


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


# --- spec 014: right of access and erasure (admins) ---------------------------------------------


@router.get("/{student_id}/export")
async def export_student(student_id: uuid.UUID, scope: AdminScope) -> JSONResponse:
    """Everything stored about the student, as a JSON attachment. The audit event commits before
    the body is returned: no audit row, no download."""
    data = await export.student_export(scope, student_id)
    audit.record(scope, AuditAction.export_downloaded, student_id, {"source": "ui"})
    await scope.session.commit()
    day = datetime.now(UTC).astimezone(kp_flow.IST).date().isoformat()
    filename = f"student-{data['student']['username']}-{day}.json"
    return JSONResponse(
        data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/{student_id}/erasure", response_model=StudentOut)
async def request_erasure(
    student_id: uuid.UUID, body: EraseIn, scope: AdminScope, admin: AdminApi
) -> StudentOut:
    return await erasure.request(scope, admin, student_id, body.confirm_username)


@router.delete("/{student_id}/erasure", response_model=StudentOut)
async def cancel_erasure(student_id: uuid.UUID, scope: AdminScope) -> StudentOut:
    return await erasure.cancel(scope, student_id)
