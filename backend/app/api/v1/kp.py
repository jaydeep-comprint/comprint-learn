"""KP questions and remediation reviews (spec 005), and the lesson's Practice step (spec 006).
Every route goes through `OrgScope`; staff previews write nothing, and the remediation routes are
student-only (403 for staff)."""

from fastapi import APIRouter

from app.api.deps import Scope
from app.schemas.kp import AnswerIn, AnswerResult, QuestionPublic, RemediationOut
from app.services import kp_flow, practice

router = APIRouter(prefix="/learn", tags=["learn"])


@router.get("/concepts/{course}/{concept}/kps/{kp}/question", response_model=QuestionPublic)
async def kp_question(course: str, concept: str, kp: str, scope: Scope) -> QuestionPublic:
    """The current question (the same one on reload). 409 `check_first` / `kp_order` /
    `kp_passed` / `kp_waiting` when the KP can't be started now."""
    return await kp_flow.current_question(scope, course, concept, kp)


@router.post("/concepts/{course}/{concept}/kps/{kp}/answer", response_model=AnswerResult)
async def kp_answer(
    course: str, concept: str, kp: str, body: AnswerIn, scope: Scope
) -> AnswerResult:
    return await kp_flow.answer(scope, course, concept, kp, body)


@router.get("/remediations/{remediation_id}", response_model=RemediationOut)
async def remediation(remediation_id: str, scope: Scope) -> RemediationOut:
    return await kp_flow.remediation_info(scope, remediation_id)


@router.get("/remediations/{remediation_id}/question", response_model=QuestionPublic)
async def remediation_question(remediation_id: str, scope: Scope) -> QuestionPublic:
    return await kp_flow.remediation_question(scope, remediation_id)


@router.post("/remediations/{remediation_id}/answer", response_model=AnswerResult)
async def remediation_answer(remediation_id: str, body: AnswerIn, scope: Scope) -> AnswerResult:
    return await kp_flow.remediation_answer(scope, remediation_id, body)


@router.get("/concepts/{course}/{concept}/practice/question", response_model=QuestionPublic)
async def practice_question(
    course: str, concept: str, scope: Scope, again: bool = False
) -> QuestionPublic:
    """The current practice attempt's question (the same one on reload). 409 `practice_locked`
    until every KP is passed; 409 `practice_passed` once passed, unless `again` (a preview-style
    re-practice that writes nothing)."""
    return await practice.practice_question(scope, course, concept, again=again)


@router.post("/concepts/{course}/{concept}/practice/answer", response_model=AnswerResult)
async def practice_answer(
    course: str, concept: str, body: AnswerIn, scope: Scope, again: bool = False
) -> AnswerResult:
    return await practice.practice_answer(scope, course, concept, body, again=again)
