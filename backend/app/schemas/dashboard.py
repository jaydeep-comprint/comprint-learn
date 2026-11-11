"""API shapes for the teacher dashboard (spec 010). Staff only.

Built from ids, display names and `item.public` only: nothing here may carry `item.answer` (answer
keys, correct option ids, solutions). Concepts are `"<course>/<slug>"` refs as elsewhere.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import UserStatus
from app.schemas.assignments import AssignmentSummary, StudentAssignmentRow
from app.schemas.content import CourseRef
from app.schemas.learn import KpStatus, OutlineConcept
from app.schemas.quiz import LastQuizOut

Window = Literal["7d", "30d", "all"]
HeatState = Literal["locked", "ready", "in_progress", "stuck", "learned"]
Band = Literal["strong", "fading", "weak", "none"]
AtRiskCode = Literal[
    "kp_fail_rate",
    "negative_xp",
    "low_xp_rate",
    "falling_memory",
    "overdue_assignment",
    "inactive",
]


class ConceptStat(BaseModel):
    concept: str
    title: str
    chapter: str
    tries: int
    students_tried: int
    fail_rate: float | None  # null until >= 3 students tried in the window
    stuck_now: int
    learned_pct: int


class AtRiskReason(BaseModel):
    code: AtRiskCode
    detail: str


class AtRiskRow(BaseModel):
    student_id: uuid.UUID
    display_name: str
    reasons: list[AtRiskReason]


class MisconceptionItem(BaseModel):
    prompt: str
    chosen_text: str | None  # the distractor's text only, never the correct option
    student_names: list[str]


class MisconceptionStat(BaseModel):
    id: uuid.UUID
    title: str
    concept: str | None
    concept_title: str | None
    chosen: int
    offered: int
    rate: float | None
    students: int
    items: list[MisconceptionItem]


class HintStudent(BaseModel):
    student_id: uuid.UUID
    display_name: str
    hints: int
    chats: int
    answered: int
    hints_per_10: float | None


class HintUse(BaseModel):
    hints: int
    chats: int
    answered: int
    hints_per_10: float | None
    top: list[HintStudent]  # top 3 by hints per 10 questions (min 5 questions)


class FlaggedThread(BaseModel):
    thread_id: uuid.UUID
    student_id: uuid.UUID
    display_name: str
    concept: str
    concept_title: str
    created_at: datetime


class PracticeShare(BaseModel):
    learn_seconds: int
    practice_seconds: int


class ClassOverview(BaseModel):
    window: Window
    students_in_scope: int
    has_course: bool
    weakest: list[ConceptStat]
    at_risk: list[AtRiskRow]
    misconceptions: list[MisconceptionStat]
    hints: HintUse
    flagged: list[FlaggedThread]
    practice_share: PracticeShare
    assignments_due: list[AssignmentSummary]
    overdue_assignments: int


class KpStat(BaseModel):
    title: str
    tries: int
    fail_rate: float | None
    hints: int


class ItemStat(BaseModel):
    prompt: str
    kind: str
    type: str
    answers: int
    correct_pct: int | None
    avg_seconds: float | None


class StudentRef(BaseModel):
    student_id: uuid.UUID
    display_name: str


class StuckStudent(StudentRef):
    reason: str


class ConceptStudents(BaseModel):
    stuck: list[StuckStudent]
    in_progress: list[StudentRef]
    learned: list[StudentRef]
    ready: int
    locked: int


class ConceptDetail(BaseModel):
    concept: str
    title: str
    kps: list[KpStat]
    items: list[ItemStat]
    misconceptions: list[MisconceptionStat]
    students: ConceptStudents


class HeatConcept(BaseModel):
    concept: str
    title: str
    learned_pct: int


class HeatChapter(BaseModel):
    title: str
    grade: int | None
    concepts: list[HeatConcept]


class HeatCell(BaseModel):
    state: HeatState
    band: Band | None


class HeatRow(BaseModel):
    student_id: uuid.UUID
    display_name: str
    cells: list[HeatCell]  # aligned to the flattened concept order of `chapters`


class Heatmap(BaseModel):
    chapters: list[HeatChapter]
    students: list[HeatRow]


class StudentStats(BaseModel):
    learn_seconds: int
    practice_seconds: int
    kp_fail_rate: float | None
    hints_per_10: float | None
    learned: int
    total: int


class StudentDetail(BaseModel):
    student_id: uuid.UUID
    display_name: str
    status: UserStatus
    # Spec 014: the Privacy card.
    username: str
    tutor_consent_at: datetime | None
    tutor_consent_form: str | None
    erase_due_at: datetime | None
    at_risk: list[AtRiskReason]
    week_xp: int
    streak_days: int
    reviews_due: int
    last_quiz: LastQuizOut | None
    stats: StudentStats
    assignments: list[StudentAssignmentRow]


class Memory(BaseModel):
    band: Band
    retrievability: float | None
    next_due: datetime | None


class KpBrief(BaseModel):
    title: str
    status: KpStatus
    fail_count: int
    reopen_at: datetime | None


class TeacherOutlineConcept(OutlineConcept):
    state: HeatState
    memory: Memory | None
    kps: list[KpBrief]


class TeacherOutlineChapter(BaseModel):
    slug: str
    title: str
    grade: int | None
    concepts: list[TeacherOutlineConcept]


class TeacherOutline(BaseModel):
    course: CourseRef | None  # null when the class subject has no active course
    chapters: list[TeacherOutlineChapter]


ActivityKind = Literal["kp", "remediation", "practice", "review", "quiz"]


class ActivityRow(BaseModel):
    kind: ActivityKind
    concept: str | None
    title: str
    outcome: Literal["passed", "failed"]
    xp: int | None
    hints: int
    answered: int
    seconds: int
    ended_at: datetime


class ThreadRow(BaseModel):
    id: uuid.UUID
    concept: str
    concept_title: str
    kp_title: str | None
    created_at: datetime
    hints_used: int
    chat_count: int
    flagged: bool


class ThreadMessage(BaseModel):
    role: str
    kind: str
    text: str | None
    status: str
    purged: bool
    created_at: datetime


class ThreadDetail(BaseModel):
    id: uuid.UUID
    concept: str
    concept_title: str
    messages: list[ThreadMessage]
