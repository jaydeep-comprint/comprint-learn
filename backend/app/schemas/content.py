"""API shapes for global content. Item shapes are built only from the stored `public` document."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict


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
