"""Python code answers (spec 006).

The browser runs the student's code on every test (visible tests and hidden tests' inputs) and
sends what came back; the server compares with the expected values it keeps. It never trusts the
client's own pass/fail and never runs the code (no sandbox: ARCHITECTURE decision 6).

`same` and `lines` are also spliced into the content validator's harness
(`app/content/code_runner.py`), so authored solutions and students are judged identically. They
must stay stdlib-only and self-contained.
"""

import json
import math
from dataclasses import dataclass
from typing import Any

MAX_OUTPUT = 10_000
MAX_CODE = 20_000
TRUNCATED = "(output truncated)"
NOT_COMPARABLE = "returned a value that can't be compared"


def same(a: object, b: object) -> bool:
    # bool is an int subclass: never let True match 1 or 1.0
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, float) or isinstance(b, float):
        return (
            isinstance(a, (int, float))
            and isinstance(b, (int, float))
            and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
        )
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.rstrip().splitlines()]


class InvalidOutputsError(ValueError):
    """Outputs that don't fit the item (count, shape or size) → 422 `invalid_response`."""


@dataclass(frozen=True)
class Output:
    """One test's output as sent by the browser (exactly one field set)."""

    value_json: str | None = None
    stdout: str | None = None
    error: str | None = None
    timeout: bool = False

    def stored(self) -> dict[str, Any]:
        """`attempt.response.outputs[i]`: `{value}` | `{stdout}` | `{error}` | `{timeout}`."""
        if self.timeout:
            return {"timeout": True}
        if self.error is not None:
            return {"error": self.error}
        if self.stdout is not None:
            return {"stdout": self.stdout}
        value, ok = _load(self.value_json)
        return {"value": value} if ok else {"error": NOT_COMPARABLE}


def _load(text: str | None) -> tuple[Any, bool]:
    if text is None:
        return None, False
    try:
        return json.loads(text, parse_constant=_reject), True
    except ValueError:
        return None, False


def _reject(name: str) -> Any:
    raise ValueError(name)  # NaN / Infinity aren't comparable


def parse_output(raw: Any) -> Output:
    """Raises `InvalidOutputsError` for anything but one of the four shapes, or oversized text."""
    if not isinstance(raw, dict) or len(raw) != 1:
        raise InvalidOutputsError("each output has exactly one field")
    ((key, val),) = raw.items()
    if key == "timeout" and val is True:
        return Output(timeout=True)
    if key in ("json", "stdout", "error") and isinstance(val, str):
        if len(val) > MAX_OUTPUT + len(TRUNCATED) + 1:
            raise InvalidOutputsError("output too long")
        if key == "json":
            return Output(value_json=val)
        return Output(stdout=val) if key == "stdout" else Output(error=val)
    raise InvalidOutputsError(f"unknown output {key!r}")


@dataclass(frozen=True)
class TestVerdict:
    passed: bool
    got: str  # what came back, for display: a JSON text, printed text, an error, or "timeout"
    status: str  # "passed" | "failed" | "error" | "timeout"


@dataclass(frozen=True)
class CodeGrade:
    correct: bool
    per_test: list[TestVerdict]
    stored_outputs: list[dict[str, Any]]


def compare(test: dict[str, Any], output: Output) -> TestVerdict:
    """One authored test (`answer.spec.tests[i]`) against one output."""
    if output.timeout:
        return TestVerdict(False, "Took too long", "timeout")
    if output.error is not None:
        return TestVerdict(False, output.error, "error")
    if test.get("expected_stdout") is not None:
        if output.stdout is None:
            return TestVerdict(False, "(nothing printed)", "failed")
        ok = lines(output.stdout) == lines(test["expected_stdout"])
        return TestVerdict(ok, output.stdout, "passed" if ok else "failed")
    value, ok = _load(output.value_json)
    if not ok:
        return TestVerdict(False, NOT_COMPARABLE, "error")
    passed = same(value, test.get("expected"))
    return TestVerdict(passed, json.dumps(value), "passed" if passed else "failed")


def grade_code(answer: dict[str, Any], raw_outputs: list[Any]) -> CodeGrade:
    """Correct = every test passes. Raises `InvalidOutputsError` (wrong count or shape)."""
    tests = answer["spec"]["tests"]
    if len(raw_outputs) != len(tests):
        raise InvalidOutputsError("one output per test")
    outputs = [parse_output(o) for o in raw_outputs]
    verdicts = [compare(t, o) for t, o in zip(tests, outputs, strict=True)]
    return CodeGrade(
        correct=all(v.passed for v in verdicts),
        per_test=verdicts,
        stored_outputs=[o.stored() for o in outputs],
    )
