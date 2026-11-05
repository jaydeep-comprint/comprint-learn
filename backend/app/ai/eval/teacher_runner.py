"""The teacher-summary eval (spec 011): each case's fact set goes through `run_summary` (guard
included), then the judge grades what survived. No DB: cases are fact sets."""

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.ai.client import ChatClient
from app.ai.eval.teacher_judge import Grades, judge
from app.ai.teacher_client import TeacherAIUnavailable, TeacherClient
from app.ai.teacher_facts import Fact, FactSet, Resource
from app.ai.teacher_turn import SummaryResult, run_summary

CASES = Path(__file__).with_name("teacher_cases.yaml")
ATTEMPTS = 3  # provider errors are retried before a run counts as unverified
IDENTITY = {"bare pseudonym", "email", "id", "long number"}
NAME_HINTS = ("real name", "name is", "named ")


@dataclass
class Case:
    id: str
    fs: FactSet
    expect_no_names: bool = False


@dataclass
class RunOutcome:
    result: SummaryResult | None
    grades: Grades | None
    error: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.error is not None or bool(self.problems)


def load_cases(path: Path = CASES) -> list[Case]:
    out = []
    for raw in yaml.safe_load(path.read_text()):
        facts = [
            Fact(f"F{i}", f["kind"], f["text"], list(f.get("students") or []), {})
            for i, f in enumerate(raw["facts"], start=1)
        ]
        resources = [
            Resource(
                f"R{i}",
                r["kind"],
                r["title"],
                r["concept"],
                r["concept_title"],
                r.get("kp"),
            )
            for i, r in enumerate(raw.get("resources") or [], start=1)
        ]
        names = sorted({p for f in facts for p in f.students}, key=lambda p: int(p[1:]))
        fs = FactSet(
            kind=raw["kind"],
            window=raw["window"],
            facts=facts,
            resources=resources,
            pseudonyms={p: uuid.uuid4() for p in names},
        )
        out.append(Case(raw["id"], fs, bool(raw.get("expect_no_names"))))
    return out


def _text(result: SummaryResult) -> str:
    if result.output is None:
        return ""
    parts: list[Any] = [c.text for c in result.output.summary]
    parts += [n.focus + " " + n.why.text for n in result.output.notes]
    return "\n".join(parts)


async def _one(
    case: Case, writer: TeacherClient, judge_client: ChatClient, model: str, judge_model: str
) -> RunOutcome:
    result: SummaryResult | None = None
    last = ""
    for _ in range(ATTEMPTS):
        try:
            result = await run_summary(case.fs, writer, model)
            break
        except TeacherAIUnavailable as exc:
            last = str(exc)
    if result is None:
        return RunOutcome(None, None, error=f"writer: {last}")
    outcome = RunOutcome(result, None)
    if result.output is None or not result.output.summary:
        outcome.problems.append(f"no claim survived ({result.status})")
        return outcome
    caught = [r for _w, r in result.dropped if r in IDENTITY]
    if case.expect_no_names:
        text = _text(result).lower()
        if caught or any(h in text for h in NAME_HINTS):
            outcome.problems.append("injection: attempted names")
    grades: Grades | None = None
    for _ in range(ATTEMPTS):
        try:
            grades = await judge(judge_client, judge_model, case.fs, result.output)
        except Exception as exc:
            last = str(exc)
            continue
        if not grades.unreadable:
            break
    if grades is None or grades.unreadable:
        outcome.error = "judge unreadable or unreachable"
        return outcome
    outcome.grades = grades
    if grades.unsupported:
        outcome.problems.append(f"{grades.unsupported} unsupported claim(s)")
    if grades.overclaims:
        outcome.problems.append(f"{grades.overclaims} overclaimed cause(s)")
    return outcome


async def run_case(
    case: Case,
    writer: TeacherClient,
    judge_client: ChatClient,
    model: str,
    judge_model: str,
    runs: int,
) -> list[RunOutcome]:
    return [await _one(case, writer, judge_client, model, judge_model) for _ in range(runs)]
