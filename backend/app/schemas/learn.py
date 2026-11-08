"""API shapes for the Learn layer (spec 004) and its spec 005 statuses (the knowledge frontier).

The check is built only from the item's `public` document (`ItemPublic.from_row`). `CheckResult` is
the only shape that carries the correct option, the explanation or a misconception's title, and it
is sent only after an attempt (or to staff after they pick).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictInt, StrictStr

from app.models import Subject
from app.schemas.content import CourseRef, OptionPublic

LessonStatus = Literal["learned", "in_progress", "ready", "locked"]
KpStatus = Literal["not_started", "in_progress", "passed", "failed"]
PracticeStatus = Literal["none", "pending", "passed"]


class ConceptRef(BaseModel):
    id: str  # "<course>/<slug>"
    title: str


class RemediationRef(BaseModel):
    """A brush-up the student owes: review (or relearn) `prereq` before `concept`'s KP reopens."""

    id: str
    kind: Literal["review", "relearn"]
    prereq: ConceptRef
    concept: ConceptRef


class HomeConcept(BaseModel):
    id: str
    title: str
    kps_passed: int
    kps_total: int
    # Spec 006: Practice counts as one more part when the concept has practice.
    parts_passed: int
    parts_total: int
    practice_left: bool = False  # every KP passed; only Practice is left
    reopen_at: datetime | None = None  # waiting concepts only


class StudentCourse(BaseModel):
    """One home card. No auto-picked "continue": the student chooses (spec 005)."""

    slug: str
    title: str
    subject: Subject
    learned: int
    total: int
    brush_up: list[RemediationRef]
    in_progress: list[HomeConcept]
    ready: list[HomeConcept]  # the first few, in outline order
    ready_count: int
    waiting: list[HomeConcept]


class Waiting(BaseModel):
    reopen_at: datetime | None


class OutlineConcept(BaseModel):
    id: str
    title: str
    summary: str
    status: LessonStatus | None  # null for staff
    prereqs: list[str]
    kps_passed: int
    kps_total: int
    parts_passed: int  # KPs passed + practice passed (spec 006)
    parts_total: int  # KPs + 1 when the concept has practice
    waiting: Waiting | None  # the next KP failed and isn't open yet
    brush_up: bool  # a remediation review is due for one of its KPs
    brush_up_id: uuid.UUID | None  # that review (the map's "Brush up first" button)
    placed: bool = False  # spec 012: learned through a placement diagnostic
    conditional: bool = False  # spec 012: placed on thin evidence ("check soon")


class OutlineChapter(BaseModel):
    slug: str
    title: str
    grade: int | None
    concepts: list[OutlineConcept]


class Outline(BaseModel):
    course: CourseRef
    chapters: list[OutlineChapter]


class LockedPrereq(BaseModel):
    id: str
    title: str
    status: LessonStatus


class CheckPublic(BaseModel):
    item_id: str
    prompt: str
    options: list[OptionPublic]


class KpOut(BaseModel):
    slug: str
    title: str
    worked_example_md: str
    status: KpStatus | None  # null for staff
    open: bool  # its questions may be started now (only a failed KP waits)
    reopen_at: datetime | None
    active: bool  # a question session is in progress (resume at its `kpq` step)


class LessonPractice(BaseModel):
    """The lesson's Practice step (spec 006)."""

    status: PracticeStatus  # none: no practice items (no `practice` step)
    active: bool  # an attempt is in progress (resume at the `practice` step)


class LessonWaiting(BaseModel):
    """The next KP failed and isn't open yet: retry later, or brush up first."""

    kp: str
    reopen_at: datetime | None
    remediations: list[RemediationRef]


class ProgressOut(BaseModel):
    seen_steps: list[str]
    last_step: str
    finished_at: datetime | None


class MisconceptionOut(BaseModel):
    title: str  # student-facing; the teacher-facing description is never sent


class CheckResult(BaseModel):
    correct: bool
    chosen: str
    correct_option: str
    explanation_md: str | None
    misconception: MisconceptionOut | None


class CheckSubmitted(CheckResult):
    already_answered: bool


class Lesson(BaseModel):
    id: str
    title: str
    summary: str
    asset_base: str
    intro_md: str
    check: CheckPublic | None
    kps: list[KpOut]
    steps: list[str]
    progress: ProgressOut | None
    check_result: CheckResult | None
    preview: bool
    concept_status: LessonStatus | None  # null for staff
    waiting: LessonWaiting | None
    practice: LessonPractice


class ProgressIn(BaseModel):
    step: StrictStr = Field(max_length=80)
    active_seconds: StrictInt = Field(ge=0)  # clamped to 600 server side


class CheckIn(BaseModel):
    option_id: StrictStr = Field(max_length=60)
    time_taken_ms: StrictInt  # clamped to 0-1,800,000 server side
