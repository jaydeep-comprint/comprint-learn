"""Pydantic models for the files in `content/` (spec 003). Unknown keys are errors.

Shapes and types only; cross-field and cross-file rules live in `app.content.validate`.
"""

import keyword
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.content import Bloom, ItemKind, ItemType
from app.models.tenancy import Subject

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
# `<concept>` inside a course, `<course>/<concept>` across courses.
REF_PATTERN = r"^([a-z0-9]+(-[a-z0-9]+)*/)?[a-z0-9]+(-[a-z0-9]+)*$"

Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN, max_length=60)]
ConceptRef = Annotated[str, StringConstraints(pattern=REF_PATTERN, max_length=121)]
Text = Annotated[str, StringConstraints(min_length=1)]
Number = int | float

__all__ = ["Bloom", "ItemKind", "ItemType"]  # DB enums, re-exported for content code


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _identifier(name: str) -> str:
    if not name.isidentifier() or keyword.iskeyword(name) or name.startswith("_"):
        raise ValueError(f"{name!r} is not a valid name (letters, digits, _; not a Python keyword)")
    return name


# --- course / chapter / misconceptions ------------------------------------------------------------


class CourseFile(_Strict):
    id: Slug
    title: Text
    subject: Subject
    chapters: list[Slug]


class Misconception(_Strict):
    id: Slug
    title: Text
    description: Text


class ChapterFile(_Strict):
    id: Slug
    title: Text
    grade: Literal[9, 10] | None = None
    concepts: list[Slug]


# --- answer specs (ARCHITECTURE decision 10) ------------------------------------------------------


class NumericAnswer(_Strict):
    value: str | Number
    unit: str | None = None
    mode: Literal["exact", "sigfig", "tolerance"]
    sigfigs: int | None = None
    rel_tol: float | None = None
    abs_tol: float | None = None
    sci_notation: bool = False


class ExpressionAnswer(_Strict):
    value: str
    variables: list[str]
    sympy_mode: Literal["exact", "equivalent", "simplified"]

    @field_validator("variables")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        return [_identifier(n) for n in v]


class McqOption(_Strict):
    id: Literal["a", "b", "c", "d", "e"]
    text: Text
    correct: bool = False
    misconception: Slug | None = None


class McqAnswer(_Strict):
    options: list[McqOption]
    shuffle: bool = True


class StepAnswer(_Strict):
    """A multistep step's answer: exactly one of numeric / expression / mcq."""

    numeric: NumericAnswer | None = None
    expression: ExpressionAnswer | None = None
    mcq: McqAnswer | None = None

    @model_validator(mode="after")
    def _one(self) -> "StepAnswer":
        if sum(x is not None for x in (self.numeric, self.expression, self.mcq)) != 1:
            raise ValueError("a step answer needs exactly one of numeric, expression or mcq")
        return self

    @property
    def type(self) -> ItemType:
        if self.numeric is not None:
            return ItemType.numeric
        return ItemType.expression if self.expression is not None else ItemType.mcq

    @property
    def spec(self) -> NumericAnswer | ExpressionAnswer | McqAnswer:
        spec = self.numeric or self.expression or self.mcq
        assert spec is not None
        return spec


class Step(_Strict):
    prompt: Text
    answer: StepAnswer


class MultistepAnswer(_Strict):
    steps: list[Step]


class CodeTest(_Strict):
    """`args` → `expected` (return value), or `stdin` → `expected_stdout` (printed output)."""

    args: list[Any] = Field(default_factory=list)
    expected: Any = None
    stdin: str | None = None
    expected_stdout: str | None = None
    visible: bool = False

    @model_validator(mode="after")
    def _one_expectation(self) -> "CodeTest":
        has_expected = "expected" in self.model_fields_set
        if has_expected == (self.expected_stdout is not None):
            raise ValueError("a test needs exactly one of expected or expected_stdout")
        if self.stdin is not None and has_expected:
            raise ValueError("stdin is only for expected_stdout tests")
        return self

    @property
    def is_stdout(self) -> bool:
        return self.expected_stdout is not None


class CodeAnswer(_Strict):
    entry: str
    starter: Text
    solution: Text
    tests: list[CodeTest]
    time_limit_ms: int = Field(default=2000, ge=100, le=10_000)

    @field_validator("entry")
    @classmethod
    def _entry(cls, v: str) -> str:
        return _identifier(v)


class AnswerSpec(_Strict):
    """`answer: {<type>: <spec>}`; the key must match the item's `type`."""

    numeric: NumericAnswer | None = None
    expression: ExpressionAnswer | None = None
    mcq: McqAnswer | None = None
    multistep: MultistepAnswer | None = None
    code: CodeAnswer | None = None


# --- items ----------------------------------------------------------------------------------------


class RangeOrChoices(_Strict):
    """`{min, max, step}` (inclusive) or `{choices: [...]}`."""

    min: Number | None = None
    max: Number | None = None
    step: Number | None = None
    choices: list[Number] | None = None

    @model_validator(mode="after")
    def _form(self) -> "RangeOrChoices":
        ranged = (self.min, self.max, self.step)
        if self.choices is not None:
            if any(x is not None for x in ranged):
                raise ValueError("use either {min, max, step} or {choices}, not both")
            if not self.choices:
                raise ValueError("choices can't be empty")
        elif any(x is None for x in ranged):
            raise ValueError("a param needs {min, max, step} or {choices}")
        else:
            assert self.min is not None and self.max is not None and self.step is not None
            if self.step <= 0:
                raise ValueError("step must be > 0")
            if self.max < self.min:
                raise ValueError("max must be >= min")
        return self


class Item(_Strict):
    id: Slug
    type: ItemType
    bloom: Bloom
    expected_minutes: float
    prompt: Text
    params: dict[str, RangeOrChoices] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    derived: dict[str, str] = Field(default_factory=dict)
    answer: AnswerSpec
    explanation: str | None = None

    @field_validator("expected_minutes")
    @classmethod
    def _minutes(cls, v: float) -> float:
        if not 0.5 <= v <= 30 or (v * 2) != int(v * 2):
            raise ValueError("expected_minutes must be 0.5-30 in steps of 0.5")
        return v

    @field_validator("params", "derived")
    @classmethod
    def _names(cls, v: dict[str, Any]) -> dict[str, Any]:
        for name in v:
            _identifier(name)
        return v

    @model_validator(mode="after")
    def _answer_matches_type(self) -> "Item":
        keys = [k for k in ItemType if getattr(self.answer, k.value) is not None]
        if keys != [self.type]:
            raise ValueError(
                f"answer must have exactly one key, {self.type.value!r} (the item type)"
            )
        return self

    @property
    def spec(self) -> NumericAnswer | ExpressionAnswer | McqAnswer | MultistepAnswer | CodeAnswer:
        spec = getattr(self.answer, self.type.value)
        assert spec is not None
        return spec  # type: ignore[no-any-return]

    @property
    def has_params(self) -> bool:
        return bool(self.params)


# --- concept --------------------------------------------------------------------------------------


class Prereq(_Strict):
    concept: ConceptRef
    weight: float


class Kp(_Strict):
    id: Slug
    title: Text
    worked_example: Text
    key_prereqs: list[ConceptRef] = Field(default_factory=list)
    items: list[Item]


class ConceptFile(_Strict):
    id: Slug
    title: Text
    summary: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    prereqs: list[Prereq] = Field(default_factory=list)
    intro: Text
    misconception_check: Item
    kps: list[Kp]
    practice: list[Item]
