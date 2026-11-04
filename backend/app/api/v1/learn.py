"""Learn layer (spec 004). Every route goes through `OrgScope`; staff previews write nothing."""

from fastapi import APIRouter, Response, status

from app.api.deps import Scope
from app.schemas.learn import (
    CheckIn,
    CheckSubmitted,
    Lesson,
    Outline,
    ProgressIn,
    ProgressOut,
    StudentCourse,
)
from app.services import learn

router = APIRouter(prefix="/learn", tags=["learn"])


@router.get("/courses", response_model=list[StudentCourse])
async def student_courses(scope: Scope) -> list[StudentCourse]:
    """The signed-in student's courses (staff: 403; they use `/courses`)."""
    return await learn.student_courses(scope)


@router.get("/courses/{slug}/outline", response_model=Outline)
async def course_outline(slug: str, scope: Scope) -> Outline:
    return await learn.outline(scope, slug)


@router.get("/concepts/{course}/{concept}", response_model=Lesson)
async def get_lesson(course: str, concept: str, scope: Scope) -> Lesson:
    return await learn.lesson(scope, course, concept)


@router.post(
    "/concepts/{course}/{concept}/progress",
    response_model=ProgressOut,
    responses={204: {"description": "Staff preview: nothing recorded"}},
)
async def post_progress(
    course: str, concept: str, body: ProgressIn, scope: Scope
) -> ProgressOut | Response:
    out = await learn.record_progress(scope, course, concept, body.step, body.active_seconds)
    return Response(status_code=status.HTTP_204_NO_CONTENT) if out is None else out


@router.post("/concepts/{course}/{concept}/check", response_model=CheckSubmitted)
async def post_check(course: str, concept: str, body: CheckIn, scope: Scope) -> CheckSubmitted:
    return await learn.submit_check(scope, course, concept, body.option_id, body.time_taken_ms)
