"""Today's reviews and scheduled reviews (spec 007). Student-only (403 for staff), through
`OrgScope`."""

from fastapi import APIRouter

from app.api.deps import Scope
from app.schemas.kp import AnswerIn, AnswerResult, QuestionPublic
from app.schemas.reviews import ReviewQueue
from app.services import reviews

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=ReviewQueue)
async def review_queue(scope: Scope) -> ReviewQueue:
    return await reviews.queue(scope)


@router.get("/{course}/{concept}/question", response_model=QuestionPublic)
async def review_question(course: str, concept: str, scope: Scope) -> QuestionPublic:
    """The review's current question (opens it when offered). 409 `review_not_due` /
    `review_cap`."""
    return await reviews.review_question(scope, course, concept)


@router.post("/{course}/{concept}/answer", response_model=AnswerResult)
async def review_answer(course: str, concept: str, body: AnswerIn, scope: Scope) -> AnswerResult:
    return await reviews.review_answer(scope, course, concept, body)
