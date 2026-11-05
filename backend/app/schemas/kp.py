"""API shapes for KP questions, remediation reviews (spec 005) and practice (spec 006).

Questions are built only from the item's `public` document, the server-rendered prompts and, for
code, the hidden tests' *inputs*. `display_answer`, `explanation_md`, a misconception's title and a
code solution appear only in `AnswerResult`, which is sent after an answer. Answer specs, params,
hidden tests' expected values and (before they're earned) solutions never reach the client.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt, StrictStr

from app.schemas.content import OptionPublic
from app.schemas.learn import ConceptRef, MisconceptionOut, RemediationRef
from app.schemas.reviews import ReviewOutcomeOut
from app.schemas.xp import XpAwardOut

SessionStatus = Literal["active", "passed", "failed"]
QuestionType = Literal["numeric", "expression", "mcq", "multistep", "code"]
StepType = Literal["numeric", "expression", "mcq"]


class StepPublic(BaseModel):
    """One step of a multi-step problem, rendered with this attempt's numbers."""

    prompt_md: str
    type: StepType
    unit: str | None
    options: list[OptionPublic] | None  # mcq: positional ids "1".."n"
    variables: list[str] | None  # expression


class StepResult(BaseModel):
    correct: bool
    display_answer: str  # the right value for these numbers
    note: str | None
    misconception: MisconceptionOut | None = None


class CodeTestPublic(BaseModel):
    """A test in authored order. `args` / `expected` are JSON text, so `2.0` stays a float and
    `True` stays a bool on the way through JavaScript. Hidden tests carry their input only."""

    visible: bool
    returns: Literal["value", "stdout"]  # what the test checks: the return value or the printout
    args: str
    stdin: str | None
    expected: str | None  # visible return-value tests only
    expected_stdout: str | None  # visible stdout tests only


class CodePublic(BaseModel):
    entry: str
    starter: str
    prefill: str | None  # practice: the student's last submitted code
    time_limit_ms: int
    tests: list[CodeTestPublic]


class QuestionPublic(BaseModel):
    session_id: str | None  # null for a staff preview
    position: int  # 1-based within the session
    item_id: str
    type: QuestionType
    prompt_md: str  # multistep: the problem stem
    unit: str | None
    unit_required: bool = False  # numeric with a unit: show the unit box
    options: list[OptionPublic] | None  # mcq: positional ids "1".."n"
    variables: list[str] | None  # expression: the names the answer may use
    steps: list[StepPublic] | None = None  # multistep
    step: int | None = None  # multistep: the step to answer now (0-based)
    step_results: list[StepResult] | None = None  # multistep: the steps answered so far
    code: CodePublic | None = None
    results: list[bool]  # this session's item results so far
    preview_seed: int | None  # staff only: send it back with `item_id`
    deadline: datetime | None = None  # spec 007: a quiz question's shared deadline


class AnswerIn(BaseModel):
    position: StrictInt = Field(ge=1)
    # The session the question was shown in (`QuestionPublic.session_id`). An answer from an
    # earlier session (another tab, before a practice retry) never lands in the current one.
    session_id: StrictStr | None = Field(default=None, max_length=60)
    # Limits the spec states (200 / 40 / 20,000 / 10,000) → 422 `invalid_response` (service).
    response: StrictStr = Field(default="", max_length=10_000)
    unit: StrictStr | None = Field(default=None, max_length=1_000)
    step: StrictInt | None = Field(default=None, ge=0, le=20)  # multistep
    code: StrictStr | None = Field(default=None, max_length=100_000)
    outputs: list[dict[str, Any]] | None = Field(default=None, max_length=100)  # code
    time_taken_ms: StrictInt  # clamped server side
    item_id: StrictStr | None = Field(default=None, max_length=60)  # staff preview only
    seed: StrictInt | None = None  # staff preview only


class CodeTestResult(BaseModel):
    visible: bool
    passed: bool
    status: Literal["passed", "failed", "error", "timeout"]
    args: str  # JSON text
    stdin: str | None
    expected: str | None  # visible tests only: JSON text, or the expected printed text
    got: str  # what came back: JSON text, printed text, an error or "Took too long"


class AnswerResult(BaseModel):
    correct: bool  # this answer (multistep: this step; see `item_correct`)
    display_answer: str  # numeric: value + unit; expression: LaTeX; mcq: positional id
    explanation_md: str | None  # multistep: after the last step
    misconception: MisconceptionOut | None
    note: str | None
    session_status: SessionStatus
    already_answered: bool
    results: list[bool]
    concept_learned: bool = False  # this pass made the concept learned
    unlocked: list[ConceptRef] = Field(default_factory=list)  # newly ready concepts
    remediations: list[RemediationRef] = Field(default_factory=list)  # created by this fail
    kp_open: bool | None = None  # passed brush-up: the KP it was for is no longer blocked
    # Spec 006
    step: int | None = None  # multistep: the step this answered
    step_results: list[StepResult] | None = None  # multistep: every step answered so far
    item_done: bool = True  # multistep: false until the last step
    item_correct: bool | None = None  # the item result, once done
    tests: list[CodeTestResult] | None = None  # code
    solution: str | None = None  # code: in KP sessions, previews, or after a practice pass
    # Spec 008: set on the answer that ended the session (and on a resend of it)
    xp: XpAwardOut | None = None
    # Spec 007: set on the answer that ended a scheduled review (and on a resend of it)
    review: ReviewOutcomeOut | None = None


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
