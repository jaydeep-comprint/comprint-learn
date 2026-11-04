"""Multi-step problems (spec 006): one item, answered one step at a time.

Each step is a numeric / expression / MCQ answer graded by the usual graders; the item is correct
when at least 75% of its steps are correct, the last one included.
"""

import math
from collections.abc import Sequence
from typing import Any

STEP_TYPES = ("numeric", "expression", "mcq")


def step_count(answer: dict[str, Any]) -> int:
    return len(answer["spec"]["steps"])


def step_type(answer: dict[str, Any], index: int) -> str:
    step_answer = answer["spec"]["steps"][index]["answer"]
    return next(t for t in STEP_TYPES if step_answer.get(t) is not None)


def step_answer_doc(answer: dict[str, Any], index: int) -> dict[str, Any]:
    """Step `index` as a stand-alone item answer document (what `grade` takes)."""
    kind = step_type(answer, index)
    spec = answer["spec"]["steps"][index]["answer"][kind]
    doc: dict[str, Any] = {"spec": spec, "explanation": None}
    if kind == "mcq":
        options = spec["options"]
        doc["correct"] = next((o["id"] for o in options if o.get("correct")), None)
        doc["misconceptions"] = {
            o["id"]: o["misconception"] for o in options if o.get("misconception")
        }
    return doc


def needed(steps: int) -> int:
    """Correct steps needed: ceil(0.75 * steps)."""
    return math.ceil(0.75 * steps)


def multistep_outcome(results: Sequence[bool], steps: int) -> bool | None:
    """The item result once every step is answered (None before that)."""
    if len(results) < steps:
        return None
    return sum(results) >= needed(steps) and bool(results[-1])
