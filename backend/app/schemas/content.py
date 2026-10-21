"""API shapes for global content. Item shapes are built only from the stored `public` document."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models import Subject


class _Public(BaseModel):
    # forbid: a key outside the public shape (an answer leaking into `public`) fails loudly.
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptionPublic(_Public):
    id: str
    text: str


class StepPublic(_Public):
    prompt: str
    type: Literal["numeric", "expression", "mcq"]
    unit: str | None = None
    options: list[OptionPublic] | None = None
    shuffle: bool | None = None


class CodeTestPublic(_Public):
    args: list[Any]
    expected: Any = None
    stdin: str | None = None
    expected_stdout: str | None = None


class CodePublic(_Public):
    entry: str
    starter: str
    tests: list[CodeTestPublic]


class _HasPublic(Protocol):
    public: dict[str, Any]


class ItemPublic(_Public):
    """What a client may see of an item: prompt, options, visible tests, unit. No answers."""

    type: Literal["numeric", "expression", "mcq", "multistep", "code"]
    prompt: str
    has_params: bool
    unit: str | None = None
    options: list[OptionPublic] | None = None
    shuffle: bool | None = None
    steps: list[StepPublic] | None = None
    code: CodePublic | None = None

    @classmethod
    def from_row(cls, row: _HasPublic) -> "ItemPublic":
        return cls.model_validate(row.public)


# --- courses and the concept graph ----------------------------------------------------------------


class CourseSummary(BaseModel):
    slug: str
    title: str
    subject: Subject
    chapter_count: int
    concept_count: int


class CourseRef(BaseModel):
    slug: str
    title: str
    subject: Subject


class ChapterOut(BaseModel):
    slug: str
    title: str
    grade: int | None
    position: int


class ConceptNode(BaseModel):
    id: str  # "<course>/<slug>"
    title: str
    summary: str
    chapter: str
    position: int
    kp_count: int


class Edge(BaseModel):
    """`from` is the prerequisite, `to` the concept that requires it."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(alias="from")
    to: str
    weight: float


class ExternalConcept(BaseModel):
    id: str
    title: str
    course: str


class CourseGraph(BaseModel):
    course: CourseRef
    chapters: list[ChapterOut]
    concepts: list[ConceptNode]
    edges: list[Edge]
    external: list[ExternalConcept]
