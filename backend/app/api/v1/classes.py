import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import StaffScope
from app.schemas.tenancy import (
    ClassIn,
    ClassOut,
    ClassPatch,
    ClassStudentOut,
    CreatedStudentOut,
    CreateStudentsIn,
    EnrollIn,
)
from app.services import tenancy
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

router = APIRouter(prefix="/classes", tags=["classes"])

AdminApi = Annotated[SupabaseAdmin, Depends(get_supabase_admin)]


@router.get("", response_model=list[ClassOut])
async def list_classes(
    scope: StaffScope, mine: bool = False, archived: bool = False
) -> list[ClassOut]:
    return await tenancy.list_classes(scope, mine=mine, archived=archived)


@router.post("", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
async def create_class(body: ClassIn, scope: StaffScope) -> ClassOut:
    return await tenancy.create_class(scope, body.name, body.subject, body.grade)


@router.get("/{class_id}", response_model=ClassOut)
async def get_class(class_id: uuid.UUID, scope: StaffScope) -> ClassOut:
    return await tenancy.get_class(scope, class_id)


@router.patch("/{class_id}", response_model=ClassOut)
async def patch_class(class_id: uuid.UUID, body: ClassPatch, scope: StaffScope) -> ClassOut:
    return await tenancy.patch_class(
        scope,
        class_id,
        name=body.name,
        subject=body.subject,
        grade=body.grade,
        archived=body.archived,
    )


@router.put("/{class_id}/teachers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_teacher(class_id: uuid.UUID, user_id: uuid.UUID, scope: StaffScope) -> None:
    await tenancy.add_class_teacher(scope, class_id, user_id)


@router.delete("/{class_id}/teachers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_teacher(class_id: uuid.UUID, user_id: uuid.UUID, scope: StaffScope) -> None:
    await tenancy.remove_class_teacher(scope, class_id, user_id)


@router.get("/{class_id}/students", response_model=list[ClassStudentOut])
async def list_class_students(class_id: uuid.UUID, scope: StaffScope) -> list[ClassStudentOut]:
    students = await tenancy.list_class_students(scope, class_id)
    return [ClassStudentOut.model_validate(s) for s in students]


@router.post(
    "/{class_id}/students",
    response_model=list[CreatedStudentOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_students(
    class_id: uuid.UUID, body: CreateStudentsIn, scope: StaffScope, admin: AdminApi
) -> list[CreatedStudentOut]:
    return await tenancy.create_students(scope, admin, class_id, body.display_names)


@router.post("/{class_id}/enrollments", status_code=status.HTTP_204_NO_CONTENT)
async def enroll(class_id: uuid.UUID, body: EnrollIn, scope: StaffScope) -> None:
    await tenancy.enroll_students(scope, class_id, body.student_ids)


@router.delete("/{class_id}/enrollments/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll(class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope) -> None:
    await tenancy.unenroll_student(scope, class_id, student_id)
