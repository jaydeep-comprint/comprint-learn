"""The server's test comparison (backend/app/grading/code.py), run by the Pyodide worker for Run.

Kept identical to the backend (tests/test_grading_code.py checks). Edit both together.
"""

import math


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
