"""Placement (spec 012). Teacher routes under `/classes/{class_id}/placement` (staff); student
routes under `/diagnostics` (students only, 403 for staff; another student's diagnostic, or one
for a class the student isn't enrolled in, is 404). Answers never return correctness."""

import uuid

from fastapi import APIRouter

from app.api.deps import Scope, StaffScope
from app.schemas.kp import QuestionPublic
from app.schemas.placement import (
    ChaptersIn,
    DiagnosticAnswerIn,
    DiagnosticResult,
    DiagnosticSaved,
    DiagnosticState,
    PlacementOverview,
    PlacementStudentRow,
    SendIn,
    SendOut,
    StudentOutcomes,
)
from app.services import placement

router = APIRouter(tags=["placement"])


@router.get("/classes/{class_id}/placement", response_model=PlacementOverview)
async def placement_overview(class_id: uuid.UUID, scope: StaffScope) -> PlacementOverview:
    """Covered chapters, the range preview and one status row per enrolled student."""
    return await placement.overview(scope, class_id)


@router.put("/classes/{class_id}/placement/chapters", response_model=PlacementOverview)
async def placement_chapters(
    class_id: uuid.UUID, body: ChaptersIn, scope: StaffScope
) -> PlacementOverview:
    """Replace the class course's covered chapters. 422 `chapter_not_in_course`;
    409 `class_archived`."""
    return await placement.set_chapters(scope, class_id, body)


@router.post("/classes/{class_id}/placement/send", response_model=SendOut)
async def placement_send(class_id: uuid.UUID, body: SendIn, scope: StaffScope) -> SendOut:
    """Send to the class or chosen students; skips anyone with an open or finished one.
    422 `placement_invalid` / `students_not_in_class`; 409 `class_archived`."""
    return await placement.send(scope, class_id, body)


@router.post(
    "/classes/{class_id}/placement/students/{student_id}/resend",
    response_model=PlacementStudentRow,
)
async def placement_resend(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope
) -> PlacementStudentRow:
    """409 `diagnostic_open` / `class_archived`; 422 `placement_invalid`."""
    return await placement.resend(scope, class_id, student_id)


@router.post(
    "/classes/{class_id}/placement/students/{student_id}/cancel",
    response_model=PlacementStudentRow,
)
async def placement_cancel(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope
) -> PlacementStudentRow:
    """Discard the open diagnostic. 409 `diagnostic_closed` / `class_archived`."""
    return await placement.cancel(scope, class_id, student_id)


@router.get("/classes/{class_id}/placement/students/{student_id}", response_model=StudentOutcomes)
async def placement_student(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: StaffScope
) -> StudentOutcomes:
    """The latest finished diagnostic's outcome per range concept."""
    return await placement.student_outcomes(scope, class_id, student_id)


@router.get("/diagnostics/current", response_model=list[DiagnosticState])
async def diagnostics_current(scope: Scope) -> list[DiagnosticState]:
    """The caller's open (sent or active) diagnostics."""
    return await placement.current(scope)


@router.get("/diagnostics/{diagnostic_id}", response_model=DiagnosticState)
async def diagnostic_state(diagnostic_id: str, scope: Scope) -> DiagnosticState:
    return await placement.state(scope, diagnostic_id)


@router.post("/diagnostics/{diagnostic_id}/start", response_model=DiagnosticState)
async def diagnostic_start(diagnostic_id: str, scope: Scope) -> DiagnosticState:
    """Freeze the range and serve the first question (idempotent once active).
    409 `diagnostic_closed`."""
    return await placement.start(scope, diagnostic_id)


@router.get("/diagnostics/{diagnostic_id}/question", response_model=QuestionPublic)
async def diagnostic_question(diagnostic_id: str, scope: Scope) -> QuestionPublic:
    """409 `diagnostic_not_started` / `diagnostic_closed`."""
    return await placement.question(scope, diagnostic_id)


@router.post("/diagnostics/{diagnostic_id}/answer", response_model=DiagnosticSaved)
async def diagnostic_answer(
    diagnostic_id: str, body: DiagnosticAnswerIn, scope: Scope
) -> DiagnosticSaved:
    """Saved, with no correctness. A resend of an answered position returns the same reply.
    409 `stale_question` / `diagnostic_closed` / `diagnostic_not_started`."""
    return await placement.answer(scope, diagnostic_id, body)


@router.get("/diagnostics/{diagnostic_id}/result", response_model=DiagnosticResult)
async def diagnostic_result(diagnostic_id: str, scope: Scope) -> DiagnosticResult:
    """409 `diagnostic_not_finished` before the end."""
    return await placement.result(scope, diagnostic_id)
