"""Code answers (spec 006): the shared comparison and `grade_code`. Pure, no DB (the reference
solutions run through the content harness, as `make content-check` does)."""

import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.cli import DEFAULT_CONTENT_ROOT
from app.content import code_runner
from app.content.hashing import split_item
from app.content.loader import load
from app.content.schema import CodeAnswer
from app.grading import code
from app.grading.code import InvalidOutputsError, grade_code, lines, same

FRONTEND_COMPARE = Path(__file__).parents[2] / "frontend/src/features/code/compare.py"


def test_same_semantics() -> None:
    assert same(0.1 + 0.2, 0.3)
    assert same(1, 1.0) and same(1.0, 1)
    assert not same(1, True) and not same(True, 1.0) and not same(1.0, True)
    assert same(True, True) and not same(True, False)
    assert same([1, [2.0, {"a": 0.30000000000000004}]], [1, [2, {"a": 0.3}]])
    assert not same([1, 2], [1, 2, 3])
    assert not same({"a": 1}, {"b": 1})
    assert not same("1", 1)
    assert not same(None, 0)


def test_lines() -> None:
    assert lines("3\n2  \n1\n\n") == lines("3\n2\n1")
    assert lines("3\n2\n") != lines("3\n 2\n")


TESTS = [
    {"args": [2], "expected": 4, "visible": True},
    {"args": [3], "expected": 6.0, "visible": False},
    {"args": [], "stdin": "x", "expected_stdout": "a\nb", "visible": False},
]
ANSWER = {"spec": {"tests": TESTS}}


def test_grade_code() -> None:
    ok = grade_code(ANSWER, [{"json": "4"}, {"json": "6"}, {"stdout": "a  \nb\n"}])
    assert ok.correct and [v.status for v in ok.per_test] == ["passed"] * 3
    assert ok.stored_outputs == [{"value": 4}, {"value": 6}, {"stdout": "a  \nb\n"}]
    bad = grade_code(ANSWER, [{"json": "4"}, {"json": "true"}, {"timeout": True}])
    assert not bad.correct
    assert [v.status for v in bad.per_test] == ["passed", "failed", "timeout"]
    nan = grade_code(ANSWER, [{"json": "NaN"}, {"error": "raised X"}, {"stdout": ""}])
    assert [v.status for v in nan.per_test] == ["error", "error", "failed"]
    assert nan.stored_outputs[0] == {"error": code.NOT_COMPARABLE}


@pytest.mark.parametrize(
    "outputs",
    [
        [{"json": "4"}],
        [{"json": "4"}, {"json": "6"}, {"json": "1"}, {"json": "1"}],
        [{"json": "4"}, {"json": "6"}, {"stdout": "x", "json": "1"}],
        [{"json": "4"}, {"json": "6"}, {"value": 1}],
        [{"json": "4"}, {"json": "6"}, {"stdout": "x" * 20_000}],
        [{"json": "4"}, {"json": "6"}, "nope"],
    ],
)
def test_invalid_outputs(outputs: list[Any]) -> None:
    with pytest.raises(InvalidOutputsError):
        grade_code(ANSWER, outputs)


def _code_items() -> list[Any]:
    bundle = load(DEFAULT_CONTENT_ROOT)
    return [
        pytest.param(item, id=f"{concept.qualified_id}/{item.id}")
        for concept in bundle.concepts
        for item in [*concept.file.practice, *(i for kp in concept.file.kps for i in kp.items)]
        if item.type.value == "code"
    ]


@pytest.mark.parametrize("item", _code_items())
def test_reference_solution_outputs_pass(item: Any) -> None:
    _, answer = split_item(item)
    spec = item.spec
    assert isinstance(spec, CodeAnswer)
    outputs = code_runner.run_outputs(spec)
    assert grade_code(answer, outputs).correct
    wrong = code_runner.run_outputs(spec, source=spec.starter)
    assert not grade_code(answer, wrong).correct


def test_harness_uses_the_shared_comparison() -> None:
    assert inspect.getsource(same) in code_runner.HARNESS
    assert inspect.getsource(lines) in code_runner.HARNESS


def _functions(source: str) -> dict[str, str]:
    """`def name(...)` blocks, normalised (no comments, annotations or blank lines)."""
    out: dict[str, str] = {}
    for block in re.split(r"\n(?=def )", source):
        if not block.startswith("def "):
            continue
        body = [
            re.sub(r"\s*#.*$", "", line).rstrip()
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        out[block.split("(")[0][4:]] = "\n".join(body)
    return out


def test_frontend_compare_matches() -> None:
    """The browser's Run check (frontend/src/features/code/compare.py) is the same code."""
    ours = _functions(inspect.getsource(same) + "\n" + inspect.getsource(lines))
    theirs = _functions(FRONTEND_COMPARE.read_text())
    assert {k: theirs.get(k) for k in ours} == ours


def test_json_text_keeps_int_and_float_apart() -> None:
    assert grade_code({"spec": {"tests": [{"args": [], "expected": 1}]}}, [{"json": "1"}]).correct
    one_float = grade_code({"spec": {"tests": [{"args": [], "expected": 1}]}}, [{"json": "1.0"}])
    assert one_float.correct  # numbers compare by value when either side is a float
    as_bool = grade_code({"spec": {"tests": [{"args": [], "expected": 1}]}}, [{"json": "true"}])
    assert not as_bool.correct
    assert json.loads("2.0") == 2.0 and isinstance(json.loads("2.0"), float)
