"""Teacher AI summaries (spec 011). Staff only (`StaffScope`); class and student ids are read
through `OrgScope` (other-school ids are 404). POST runs the model; GET never does."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.ai.teacher_client import TeacherClient, get_teacher_client
from app.api.deps import StaffScope
from app.schemas.dashboard import Window
from app.schemas.teacher_ai import Summary, SummaryState
from app.services import teacher_ai

router = APIRouter(prefix="/classes/{class_id}", tags=["teacher-ai"])

Client = Annotated[TeacherClient | None, Depends(get_teacher_client)]


@router.get("/summary", response_model=SummaryState)
async def class_summary(
    class_id: uuid.UUID, scope: StaffScope, client: Client, window: Window = "7d"
) -> SummaryState:
    return await teacher_ai.get_class_summary(scope, class_id, window, client)


@router.post("/summary", response_model=Summary, status_code=201)
async def create_class_summary(
    class_id: uuid.UUID, scope: StaffScope, client: Client, window: Window = "7d"
) -> Summary:
    return await teacher_ai.create_class_summary(scope, class_id, window, client)


@router.get("/students/{student_id}/summary", response_model=SummaryState)
async def student_summary(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope, client: Client
) -> SummaryState:
    return await teacher_ai.get_student_summary(scope, class_id, student_id, client)


@router.post("/students/{student_id}/summary", response_model=Summary, status_code=201)
async def create_student_summary(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope, client: Client
) -> Summary:
    return await teacher_ai.create_student_summary(scope, class_id, student_id, client)
