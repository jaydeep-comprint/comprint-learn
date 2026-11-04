"""Server-side answer checking (spec 005; 006 adds units, multistep and code).

Pure functions, no DB access: `grade(item_type, answer_doc, values, response, shown=...)` takes the
item's stored `answer` document, the values sampled from the attempt's seed and the raw response.
Answer specs never leave the server; only `GradeResult` (sent after an answer) describes them.
"""

from dataclasses import dataclass
from typing import Any

from app.content.params import Value
from app.grading.expression import grade_expression
from app.grading.mcq import InvalidOptionError, ShownOptions, grade_mcq
from app.grading.numeric import grade_numeric

GRADABLE_TYPES = frozenset({"numeric", "expression", "mcq"})
MAX_RESPONSE = 200

__all__ = [
    "GRADABLE_TYPES",
    "MAX_RESPONSE",
    "GradeResult",
    "InvalidOptionError",
    "ShownOptions",
    "grade",
]


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    display_answer: str  # numeric: value + unit; expression: LaTeX; mcq: the positional id
    note: str | None = None
    misconception: str | None = None  # slug of a tagged wrong MCQ option
    chosen: str | None = None  # mcq: the authored option id (stored on the attempt)


def grade(
    item_type: str,
    answer: dict[str, Any],
    values: dict[str, Value],
    response: str,
    *,
    shown: ShownOptions | None = None,
) -> GradeResult:
    """Raises `InvalidOptionError` for an MCQ id that wasn't shown; other bad input is wrong."""
    spec = answer.get("spec") or {}
    if item_type == "numeric":
        n = grade_numeric(spec, values, response)
        return GradeResult(n.correct, n.display_answer, n.note)
    if item_type == "expression":
        e = grade_expression(spec, values, response)
        return GradeResult(e.correct, e.display_answer, e.note)
    if item_type == "mcq":
        if shown is None:
            raise ValueError("mcq grading needs the shown options")
        m = grade_mcq(answer, shown, response)
        return GradeResult(
            m.correct,
            m.display_answer,
            None,
            None if m.correct else m.misconception,
            m.chosen,
        )
    raise ValueError(f"{item_type} items aren't graded on the server yet")
