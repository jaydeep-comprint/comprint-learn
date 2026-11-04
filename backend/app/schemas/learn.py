"""API shapes for the Learn layer (spec 004).

The check is built only from the item's `public` document (`ItemPublic.from_row`). `CheckResult` is
the only shape that carries the correct option, the explanation or a misconception's title, and it
is sent only after an attempt (or to staff after they pick).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictInt, StrictStr

from app.models import Subject
from app.schemas.content import CourseRef, OptionPublic

LessonStatus = Literal["finished", "in_progress", "ready", "locked"]


class ConceptRef(BaseModel):
    id: str  # "<course>/<slug>"
    title: str


class StudentCourse(BaseModel):
    slug: str
    title: str
    subject: Subject
    finished: int
    total: int
    continue_: ConceptRef | None = Field(serialization_alias="continue")


class OutlineConcept(BaseModel):
    id: str
    title: str
    summary: str
    status: LessonStatus | None  # null for staff
    prereqs: list[str]


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


class ProgressIn(BaseModel):
    step: StrictStr = Field(max_length=80)
    active_seconds: StrictInt = Field(ge=0)  # clamped to 600 server side


class CheckIn(BaseModel):
    option_id: StrictStr = Field(max_length=60)
    time_taken_ms: StrictInt  # clamped to 0-1,800,000 server side
