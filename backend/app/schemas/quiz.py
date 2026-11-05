"""The mixed timed quiz (spec 007). Answers and explanations appear only in `QuizResult`, after
the quiz has finished."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.learning import XpGrade
from app.models.tenancy import Subject
from app.schemas.learn import ConceptRef


class QuizState(BaseModel):
    id: str
    status: Literal["pending", "active", "finished", "cancelled"]
    total: int  # questions (pending: the planned count, at most 10)
    minutes: float  # 1.5 per question
    deadline: datetime | None
    seconds_left: int | None  # active only: computed on the server, so client clocks don't matter
    answered: int


class QuizSaved(BaseModel):
    saved: Literal[True] = True
    answered: int
    finished: bool


class QuizSubjectXp(BaseModel):
    subject: Subject
    amount: int
    grade: XpGrade


class QuizXpOut(BaseModel):
    """The quiz's XP: the total (the toast) and one award per subject (the result)."""

    amount: int
    base_minutes: Decimal
    goal_met_today: bool
    subjects: list[QuizSubjectXp]


class QuizResultItem(BaseModel):
    position: int
    concept: ConceptRef
    type: str
    prompt_md: str
    response: str | None  # what the student answered (MCQ: the option text); null = unanswered
    correct: bool
    display_answer: str  # the correct answer for their numbers (MCQ: the option text)
    explanation_md: str | None


class QuizResult(BaseModel):
    correct: int
    total: int
    xp: QuizXpOut | None
    items: list[QuizResultItem]
    review_concepts: list[ConceptRef]  # missed: added to Today's reviews


class LastQuizOut(BaseModel):
    score_pct: int
    finished_on: datetime
