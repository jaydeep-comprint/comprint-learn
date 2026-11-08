"""Teacher AI summaries (spec 011). Names are filled in on read; the model never saw them."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.dashboard import Window

Blocked = Literal["fresh", "busy", "teacher_cap", "school_cap", "archived", "not_enough_data"]
LinkKind = Literal[
    "concept", "misconception", "student", "assignment", "overview_card", "student_section"
]


class FactLink(BaseModel):
    """Where a citation chip opens. `concept` is "<course>/<slug>"; `student_id` is null when the
    student is no longer in the class."""

    kind: LinkKind
    concept: str | None = None
    id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    card: str | None = None
    section: str | None = None


class FactOut(BaseModel):
    id: str
    text: str
    link: FactLink


class ClaimOut(BaseModel):
    text: str
    citations: list[str]


class ResourceOut(BaseModel):
    id: str
    kind: Literal["lesson", "worked_example"]
    title: str
    concept: str  # "<concept course>/<slug>"
    concept_title: str
    kp: str | None  # KP slug: open the lesson at `kp:<slug>`
    available: bool  # false when the content was retired: render as plain text
    in_course: bool  # in the class course (can be assigned)


class StudentRef(BaseModel):
    student_id: uuid.UUID
    display_name: str


class AssignPrefill(BaseModel):
    """For 010's AssignmentDialog: class-course concepts, and students (null = whole class)."""

    concepts: list[str]
    student_ids: list[uuid.UUID] | None


class NoteOut(BaseModel):
    focus: str
    why: ClaimOut
    revisit: list[ResourceOut]
    group: list[StudentRef]
    assign: AssignPrefill


class Summary(BaseModel):
    id: uuid.UUID
    kind: Literal["class", "student"]
    window: Window
    status: Literal["ok", "partial"]
    created_at: datetime
    created_by_name: str
    claims: list[ClaimOut]
    notes: list[NoteOut]
    facts: list[FactOut]  # only the cited ones


class SummaryState(BaseModel):
    enabled: bool
    enough_data: bool
    summary: Summary | None
    stale: bool
    can_regenerate: bool
    blocked: Blocked | None
    daily_left: int
    resets_at: datetime
