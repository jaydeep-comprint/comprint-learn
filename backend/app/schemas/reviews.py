"""Today's reviews and review results (spec 007). Ids, dates and titles only."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.models.tenancy import Subject
from app.schemas.learn import ConceptRef


class ReviewOffer(BaseModel):
    course: str
    concept: ConceptRef
    subject: Subject
    reason: Literal["schedule", "quiz_miss"]
    due_on: date
    active: bool  # a review session is open for it


class ReviewQueue(BaseModel):
    cap: int
    done_today: int
    offered: list[ReviewOffer]
    more_due: int  # due scheduled cards beyond today's cap (they roll over)
    next_due_on: date | None  # when nothing is offered: the next day a review comes up
    has_cards: bool  # the student has at least one card (else the home card is hidden)


class ReviewOutcomeOut(BaseModel):
    """On the answer that ends a review: the rating and when it comes back (null = relearn)."""

    rating: Literal["again", "hard", "good"]
    next_due: date | None
    relearn: bool
