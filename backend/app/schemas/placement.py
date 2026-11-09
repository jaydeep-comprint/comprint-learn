"""Placement (spec 012): the teacher's Placement tab and the student's diagnostic. Responses carry
ids, display names and `item.public` text only; answers never return correctness."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictStr, model_validator

from app.schemas.content import CourseRef
from app.schemas.kp import AnswerIn
from app.schemas.learn import ConceptRef

PlacementStatus = Literal["not_sent", "sent", "active", "finished", "cancelled"]
Outcome = Literal["learned", "conditional", "demoted", "unchanged"]


class PlacementChapter(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    grade: int | None
    covered: bool


class RangePreview(BaseModel):
    concepts: int  # covered chapters' concepts + all their prerequisite ancestors
    prereqs: int  # of those, outside the covered chapters (earlier chapters, other courses)
    askable: int  # concepts a placement check can ask about


class PlacementCounts(BaseModel):
    learned: int
    conditional: int
    demoted: int


class PlacementStudentRow(BaseModel):
    student_id: uuid.UUID
    display_name: str
    status: PlacementStatus  # the latest diagnostic's
    diagnostic_id: uuid.UUID | None
    sent_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    answered: int
    # The latest *finished* diagnostic's outcome (it may be older than the latest status).
    result_at: datetime | None
    counts: PlacementCounts | None


class PlacementOverview(BaseModel):
    course: CourseRef | None  # null: no course for the class subject
    archived: bool
    chapters: list[PlacementChapter]  # the class course's, in outline order
    range: RangePreview
    students: list[PlacementStudentRow]


class ChaptersIn(BaseModel):
    chapter_ids: list[uuid.UUID] = Field(max_length=200)


class SendIn(BaseModel):
    """The whole class (`all_students`, or no `student_ids`) or the chosen students."""

    all_students: StrictBool = False
    student_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class SendOut(BaseModel):
    sent: int
    skipped: int  # already had an open or finished diagnostic for the class


class ConceptOutcome(BaseModel):
    concept: ConceptRef
    outcome: Outcome


class StudentOutcomes(BaseModel):
    student_id: uuid.UUID
    display_name: str
    diagnostic_id: uuid.UUID | None  # the latest finished one
    finished_at: datetime | None
    concepts: list[ConceptOutcome]


# --- student --------------------------------------------------------------------------------------

DiagnosticStatusOut = Literal["sent", "active", "finished", "cancelled"]


class DiagnosticState(BaseModel):
    id: uuid.UUID
    status: DiagnosticStatusOut
    class_name: str
    course: CourseRef | None
    answered: int
    max_questions: int
    empty: bool = False  # finished at start: nothing to check right now


class DiagnosticAnswerIn(AnswerIn):
    """A diagnostic answer: the shared answer fields, or `idk: true` ("I don't know")."""

    session_id: StrictStr = Field(max_length=60)
    idk: StrictBool = False

    @model_validator(mode="after")
    def _answer_or_idk(self) -> "DiagnosticAnswerIn":
        if not self.idk and not self.response.strip():
            raise ValueError("Send an answer or `idk: true`.")
        return self


class DiagnosticSaved(BaseModel):
    finished: bool
    answered: int


class DiagnosticResult(BaseModel):
    answered: int
    learned: list[ConceptRef]
    conditional: list[ConceptRef]  # "to check soon"
    to_learn: list[ConceptRef]  # range concepts not learned now (demoted included)
