"""API shapes for teacher assignments and the student's Focus Mode (spec 010)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

StudentStatus = Literal[
    "done_early", "done_on_time", "done_late", "overdue", "in_progress", "not_started"
]
PathStatus = Literal["in_progress", "stuck", "ready", "locked"]


class AssignmentIn(BaseModel):
    """Create. Lengths are checked in the service so the errors carry the spec's codes."""

    concepts: list[str] = Field(max_length=100)
    due_date: date
    note: str | None = Field(default=None, max_length=1000)
    student_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class AssignmentPatch(BaseModel):
    """Omitted fields are unchanged; `student_ids: null` means the whole class."""

    concepts: list[str] | None = Field(default=None, max_length=100)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)
    student_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class TargetRef(BaseModel):
    concept: str
    title: str


class StatusCounts(BaseModel):
    done: int = 0  # every done student (on time, late and already learned)
    done_late: int = 0
    already_learned: int = 0
    overdue: int = 0
    in_progress: int = 0
    not_started: int = 0
    total: int = 0


class AssignmentSummary(BaseModel):
    id: uuid.UUID
    title: str
    concepts: list[TargetRef]
    content_available: bool  # false when no target is left (retired or outside the course)
    due_date: date
    note: str | None
    all_students: bool
    student_ids: list[uuid.UUID]  # as stored (empty for the whole class)
    counts: StatusCounts
    active: bool  # not deleted and due date >= today (IST)
    created_at: datetime


class NextConcept(BaseModel):
    concept: str
    title: str


class AssignmentStudentRow(BaseModel):
    student_id: uuid.UUID
    display_name: str
    status: StudentStatus
    done_at: datetime | None
    learned: int
    total: int
    next: NextConcept | None


class AssignmentDetail(AssignmentSummary):
    students: list[AssignmentStudentRow]


class StudentAssignmentRow(BaseModel):
    """One of a student's assignments, on the teacher's student page."""

    id: uuid.UUID
    title: str
    due_date: date
    status: StudentStatus
    done_at: datetime | None
    learned: int
    total: int
    next: NextConcept | None


class PathStep(BaseModel):
    concept: str
    course: str
    title: str
    status: PathStatus
    waiting: bool
    target: bool


class FocusNext(BaseModel):
    concept: str
    course: str
    title: str
    brush_up_id: uuid.UUID | None


class MyAssignment(BaseModel):
    id: uuid.UUID
    title: str
    class_name: str
    course: str  # the class course slug
    due_date: date
    note: str | None
    status: StudentStatus
    done_at: datetime | None
    learned: int
    total: int
    path: list[PathStep]
    next: FocusNext | None
