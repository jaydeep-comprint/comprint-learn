"""The mixed timed quiz (spec 007). Student-only (403 for staff); another student's quiz is 404.
No answer key appears before `GET /quizzes/{id}/result`."""

from fastapi import APIRouter

from app.api.deps import Scope
from app.schemas.kp import AnswerIn, QuestionPublic
from app.schemas.quiz import QuizResult, QuizSaved, QuizState
from app.services import quiz

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.get("/current", response_model=QuizState | None)
async def current_quiz(scope: Scope) -> QuizState | None:
    """The pending or active quiz, or null."""
    return await quiz.current(scope)


@router.get("/{quiz_id}", response_model=QuizState)
async def quiz_state(quiz_id: str, scope: Scope) -> QuizState:
    return await quiz.state(scope, quiz_id)


@router.post("/{quiz_id}/start", response_model=QuizState)
async def start_quiz(quiz_id: str, scope: Scope) -> QuizState:
    """Start the timer (idempotent once started)."""
    return await quiz.start(scope, quiz_id)


@router.get("/{quiz_id}/question", response_model=QuestionPublic)
async def quiz_question(quiz_id: str, scope: Scope) -> QuestionPublic:
    """409 `quiz_not_started` / `quiz_over`."""
    return await quiz.question(scope, quiz_id)


@router.post("/{quiz_id}/answer", response_model=QuizSaved)
async def quiz_answer(quiz_id: str, body: AnswerIn, scope: Scope) -> QuizSaved:
    """Saved, with no correctness. 409 `quiz_over` after the deadline + 30 s."""
    return await quiz.answer(scope, quiz_id, body)


@router.get("/{quiz_id}/result", response_model=QuizResult)
async def quiz_result(quiz_id: str, scope: Scope) -> QuizResult:
    """409 `quiz_not_finished` before the end."""
    return await quiz.result(scope, quiz_id)
