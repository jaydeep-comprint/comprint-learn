"""The model's JSON output for a teacher summary (spec 011). JSON mode guarantees JSON, not this
shape, so every reply is validated here; lengths and references are the guard's job."""

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Claim(_Out):
    text: str
    facts: list[str] = Field(default_factory=list)


class Note(_Out):
    focus: str
    why: Claim
    revisit: list[str] = Field(default_factory=list)
    group: list[str] = Field(default_factory=list)
    group_facts: list[str] = Field(default_factory=list)


class ModelOutput(_Out):
    summary: list[Claim]
    notes: list[Note] = Field(default_factory=list)
