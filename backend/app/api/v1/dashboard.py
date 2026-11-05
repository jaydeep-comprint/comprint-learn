"""Teacher dashboard (spec 010). Staff only (`StaffScope`); every class and student id is read
through `OrgScope` (other-school ids are 404). Reads never write learning state."""

import uuid
from datetime import datetime

from fastapi import APIRouter

from app.api.deps import StaffScope
from app.schemas.dashboard import (
    ActivityRow,
    ClassOverview,
    ConceptDetail,
    ConceptStat,
    Heatmap,
    MisconceptionStat,
    StudentDetail,
    TeacherOutline,
    ThreadDetail,
    ThreadRow,
    Window,
)
from app.services import dashboard

router = APIRouter(prefix="/classes/{class_id}", tags=["dashboard"])


@router.get("/overview", response_model=ClassOverview)
async def overview(class_id: uuid.UUID, scope: StaffScope, window: Window = "7d") -> ClassOverview:
    return await dashboard.overview(scope, class_id, window)


@router.get("/concepts", response_model=list[ConceptStat])
async def concepts(
    class_id: uuid.UUID, scope: StaffScope, window: Window = "7d"
) -> list[ConceptStat]:
    return await dashboard.concepts(scope, class_id, window)


@router.get("/concepts/{course}/{concept}", response_model=ConceptDetail)
async def concept_detail(
    class_id: uuid.UUID, course: str, concept: str, scope: StaffScope, window: Window = "7d"
) -> ConceptDetail:
    return await dashboard.concept_detail(scope, class_id, course, concept, window)


@router.get("/misconceptions", response_model=list[MisconceptionStat])
async def misconceptions(
    class_id: uuid.UUID, scope: StaffScope, window: Window = "7d"
) -> list[MisconceptionStat]:
    return await dashboard.misconceptions(scope, class_id, window)


@router.get("/heatmap", response_model=Heatmap)
async def heatmap(class_id: uuid.UUID, scope: StaffScope) -> Heatmap:
    return await dashboard.heatmap(scope, class_id)


@router.get("/students/{student_id}", response_model=StudentDetail)
async def student_detail(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope
) -> StudentDetail:
    return await dashboard.student_detail(scope, class_id, student_id)


@router.get("/students/{student_id}/outline", response_model=TeacherOutline)
async def student_outline(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope
) -> TeacherOutline:
    return await dashboard.student_outline(scope, class_id, student_id)


@router.get("/students/{student_id}/activity", response_model=list[ActivityRow])
async def student_activity(
    class_id: uuid.UUID,
    student_id: uuid.UUID,
    scope: StaffScope,
    before: datetime | None = None,
) -> list[ActivityRow]:
    return await dashboard.student_activity(scope, class_id, student_id, before)


@router.get("/students/{student_id}/tutor", response_model=list[ThreadRow])
async def tutor_threads(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope
) -> list[ThreadRow]:
    return await dashboard.tutor_threads(scope, class_id, student_id)


@router.get("/students/{student_id}/tutor/{thread_id}", response_model=ThreadDetail)
async def tutor_thread(
    class_id: uuid.UUID, student_id: uuid.UUID, thread_id: uuid.UUID, scope: StaffScope
) -> ThreadDetail:
    return await dashboard.tutor_thread(scope, class_id, student_id, thread_id)
