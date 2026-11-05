"""Teacher assignments (spec 010): staff CRUD under a class, and the student's
`/me/assignments` (Focus Mode; 403 for staff). Everything goes through `OrgScope`."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import Scope, StaffScope
from app.schemas.assignments import (
    AssignmentDetail,
    AssignmentIn,
    AssignmentPatch,
    AssignmentSummary,
    MyAssignment,
)
from app.services import assignments

router = APIRouter(tags=["assignments"])


@router.get("/classes/{class_id}/assignments", response_model=list[AssignmentSummary])
async def list_assignments(class_id: uuid.UUID, scope: StaffScope) -> list[AssignmentSummary]:
    return await assignments.class_assignments(scope, class_id)


@router.post(
    "/classes/{class_id}/assignments",
    response_model=AssignmentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    class_id: uuid.UUID, body: AssignmentIn, scope: StaffScope
) -> AssignmentSummary:
    """422 `assignment_invalid` / `concept_not_in_course` / `students_not_in_class`; 409
    `class_archived`."""
    return await assignments.create(scope, class_id, body)


@router.get("/classes/{class_id}/assignments/{assignment_id}", response_model=AssignmentDetail)
async def get_assignment(
    class_id: uuid.UUID, assignment_id: uuid.UUID, scope: StaffScope
) -> AssignmentDetail:
    return await assignments.assignment_detail(scope, class_id, assignment_id)


@router.patch("/classes/{class_id}/assignments/{assignment_id}", response_model=AssignmentSummary)
async def patch_assignment(
    class_id: uuid.UUID, assignment_id: uuid.UUID, body: AssignmentPatch, scope: StaffScope
) -> AssignmentSummary:
    return await assignments.patch(scope, class_id, assignment_id, body)


@router.delete(
    "/classes/{class_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_assignment(
    class_id: uuid.UUID, assignment_id: uuid.UUID, scope: StaffScope
) -> Response:
    await assignments.remove(scope, class_id, assignment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/assignments", response_model=list[MyAssignment])
async def my_assignments(scope: Scope) -> list[MyAssignment]:
    return await assignments.my_assignments(scope)
