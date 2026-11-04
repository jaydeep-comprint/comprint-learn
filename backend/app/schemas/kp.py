"""API shapes for KP questions and remediation reviews (spec 005).

Questions are built only from the item's `public` document plus the server-rendered prompt.
`display_answer`, `explanation_md` and a misconception's title appear only in `AnswerResult`, which
is sent after an answer. Answer specs, params and solutions never reach the client.
"""

from typing import Literal

from pydantic import BaseModel, Field, StrictInt, StrictStr

from app.schemas.content import OptionPublic
from app.schemas.learn import ConceptRef, MisconceptionOut, RemediationRef

SessionStatus = Literal["active", "passed", "failed"]


class QuestionPublic(BaseModel):
    session_id: str | None  # null for a staff preview
    position: int  # 1-based within the session
    item_id: str
    type: Literal["numeric", "expression", "mcq"]
    prompt_md: str
    unit: str | None
    options: list[OptionPublic] | None  # mcq: positional ids "1".."n"
    variables: list[str] | None  # expression: the names the answer may use
    results: list[bool]  # this session's answers so far
    preview_seed: int | None  # staff only: send it back with `item_id`


class AnswerIn(BaseModel):
    position: StrictInt = Field(ge=1)
    response: StrictStr = Field(max_length=10_000)  # > 200 → 422 `invalid_response` (service)
    time_taken_ms: StrictInt  # clamped server side
    item_id: StrictStr | None = Field(default=None, max_length=60)  # staff preview only
    seed: StrictInt | None = None  # staff preview only


class AnswerResult(BaseModel):
    correct: bool
    display_answer: str  # numeric: value + unit; expression: LaTeX; mcq: the positional id
    explanation_md: str | None
    misconception: MisconceptionOut | None
    note: str | None
    session_status: SessionStatus
    already_answered: bool
    results: list[bool]
    concept_learned: bool = False  # this pass made the concept learned
    unlocked: list[ConceptRef] = Field(default_factory=list)  # newly ready concepts
    remediations: list[RemediationRef] = Field(default_factory=list)  # created by this fail
    kp_open: bool | None = None  # passed brush-up: the KP it was for is no longer blocked


class KpWaiting(BaseModel):
    """Body extra of 409 `kp_waiting`."""

    reopen_at: str | None
    remediations: list[RemediationRef]


class RemediationOut(BaseModel):
    id: str
    state: Literal["review_due", "relearn", "resolved"]
    kind: Literal["review", "relearn"]
    prereq: ConceptRef
    concept: ConceptRef  # the concept whose KP failed
    kp_title: str
