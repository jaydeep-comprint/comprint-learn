from typing import Any

import pytest

from app.content.code_runner import check_defines_entry, run_tests
from app.content.schema import CodeAnswer


def _spec(solution: str, tests: list[dict[str, Any]], **kw: Any) -> CodeAnswer:
    return CodeAnswer.model_validate(
        {"entry": "f", "starter": "def f(n):\n    pass\n", "solution": solution, "tests": tests}
        | kw
    )


TESTS = [
    {"args": [1], "expected": 2, "visible": True},
    {"args": [5], "expected": 10},
    {"args": [-2], "expected": -4},
]


def test_passing_solution() -> None:
    assert run_tests(_spec("def f(n):\n    print('noise')\n    return 2 * n\n", TESTS)) == []


def test_failing_test_reports_its_index() -> None:
    [failure] = run_tests(_spec("def f(n):\n    return 2 * n if n != 5 else 11\n", TESTS))
    assert (failure.index, failure.message) == (1, "returned 11, expected 10")


def test_exception_is_reported() -> None:
    [failure] = run_tests(_spec("def f(n):\n    return 2 * n if n > 0 else 1 // 0\n", TESTS))
    assert failure.index == 2
    assert failure.message == "raised ZeroDivisionError: integer division or modulo by zero"


def test_timeout_is_reported_and_other_tests_still_run() -> None:
    solution = "def f(n):\n    while n == 5:\n        pass\n    return 2 * n\n"
    failures = run_tests(_spec(solution, TESTS, time_limit_ms=200))
    assert [(f.index, f.message) for f in failures] == [(1, "timed out after 200 ms")]


def test_broad_except_cannot_swallow_the_time_limit() -> None:
    solution = (
        "def f(n):\n    try:\n        while True:\n            pass\n"
        "    except Exception:\n        return 2 * n\n"
    )
    failures = run_tests(_spec(solution, TESTS[:1], time_limit_ms=200))
    assert [f.index for f in failures] == [0]


def test_stdout_task() -> None:
    tests: list[dict[str, Any]] = [
        {"stdin": "3\n", "expected_stdout": "1\n2\n3\n", "visible": True},
        {"stdin": "1\n", "expected_stdout": "1"},
        {"stdin": "2\n", "expected_stdout": "1\n2\n"},
    ]
    good = "def f():\n    for i in range(int(input())):\n        print(i + 1)\n"
    assert run_tests(_spec(good, tests, starter="def f():\n    pass\n")) == []
    bad = "def f():\n    print(int(input()))\n"
    failures = run_tests(_spec(bad, tests, starter="def f():\n    pass\n"))
    assert [f.index for f in failures] == [0, 2]
    assert failures[0].message == "printed '3', expected '1\\n2\\n3'"


def test_missing_entry_and_syntax_errors() -> None:
    [failure] = run_tests(_spec("def g(n):\n    return n\n", TESTS))
    assert (failure.index, failure.message) == (-1, "doesn't define a function f()")
    [failure] = run_tests(_spec("def f(n) return n\n", TESTS))
    assert failure.index == -1 and "SyntaxError" in failure.message


def test_starter_must_define_entry() -> None:
    assert check_defines_entry(_spec("def f(n):\n    return n\n", TESTS)) == []
    spec = _spec("def f(n):\n    return n\n", TESTS, starter="# write f here\n")
    [failure] = check_defines_entry(spec)
    assert failure.message == "doesn't define a function f()"


@pytest.mark.parametrize(
    ("got", "expected"), [("[1, 2]", [1, 2]), ("(1, 2)", [1, 2]), ("0.1 + 0.2", 0.3)]
)
def test_json_comparison(got: str, expected: Any) -> None:
    tests = [{"args": [0], "expected": expected, "visible": True}] * 3
    assert run_tests(_spec(f"def f(n):\n    return {got}\n", tests)) == []


def test_bool_is_not_int() -> None:
    tests = [{"args": [0], "expected": 1, "visible": True}] * 3
    assert len(run_tests(_spec("def f(n):\n    return True\n", tests))) == 3
