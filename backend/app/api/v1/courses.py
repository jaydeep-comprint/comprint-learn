"""Global content (spec 003): any signed-in user, any school. Never returns items or answers."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.schemas.content import CourseGraph, CourseSummary
from app.services import content

router = APIRouter(prefix="/courses", tags=["courses"])

# Content is the same for every school, so these routes skip OrgScope
# (tests/test_route_scoping.py: GLOBAL_CONTENT).
SignedIn = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("", response_model=list[CourseSummary])
async def list_courses(_user: SignedIn, session: SessionDep) -> list[CourseSummary]:
    return await content.list_courses(session)


@router.get("/{slug}/graph", response_model=CourseGraph)
async def course_graph(slug: str, _user: SignedIn, session: SessionDep) -> CourseGraph:
    return await content.course_graph(session, slug)
