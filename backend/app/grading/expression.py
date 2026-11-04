"""Expression answers (spec 005), parsed with the app's own safe AST walker (never `parse_expr`).

`simplify` can take unbounded time on adversarial input and a SymPy call can't be interrupted in a
thread, so `equivalent`/`simplified` checks run in a small process pool with a time limit. On a
timeout the pool is terminated and recreated, and `equivalent` falls back to a numeric check.
"""

import atexit
import logging
import multiprocessing
import random
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.pool import Pool
from typing import Any

import sympy

from app.content import params
from app.content.params import ExpressionError, Value

log = logging.getLogger(__name__)

MINUS, TIMES, DOT = "\N{MINUS SIGN}", "\N{MULTIPLICATION SIGN}", "\N{MIDDLE DOT}"
NOTE_UNREADABLE = "Couldn't read that expression"
NOTE_SIMPLIFY = "Simplify your answer"
HINT = "Use ^ for powers, e.g. 3x^2 + 2"
MAX_INPUT = 200
MAX_EXPONENT = 100
TIME_LIMIT_S = 1.0
WARMUP_S = 60.0
NUMERIC_POINTS = 5
NUMERIC_TOL = 1e-9

_TOKEN = re.compile(r"\s+|\d+\.?\d*|\.\d+|[A-Za-z_][A-Za-z0-9_]*|\*\*|.", re.DOTALL)


def _kind(tok: str) -> str:
    if tok[0].isdigit() or tok[0] == ".":
        return "num" if tok != "." else "op"
    if tok[0].isalpha() or tok[0] == "_":
        return "name"
    return tok


def preprocess(text: str) -> str:
    """`^` → `**` and implicit multiplication: `2x`, `3(x+1)`, `(x+1)(x-1)`, `(x+1)x`.

    A whitelisted function name followed by `(` is a call, not a product."""
    text = text.replace(MINUS, "-").replace(TIMES, "*").replace(DOT, "*").replace("^", "**").strip()
    out: list[str] = []
    prev: str | None = None
    for tok in _TOKEN.findall(text):
        if tok.isspace():
            out.append(tok)
            continue
        kind = _kind(tok)
        if prev is not None:
            pk = _kind(prev)
            implicit = (
                (pk == "num" and kind in ("name", "("))
                or (pk == "name" and kind == "(" and prev not in params.FUNCTIONS)
                or (pk == ")" and kind in ("(", "name", "num"))
            )
            if implicit:
                out.append("*")
        out.append(tok)
        prev = tok
    return "".join(out)


def parse_student(text: str, variables: list[str]) -> Any:
    """The student's expression; raises `ExpressionError` if it can't be read safely."""
    if len(text) > MAX_INPUT or not text.strip():
        raise ExpressionError("expression is too long or empty")
    names = {v: sympy.Symbol(v) for v in variables}
    expr = params.parse(preprocess(text), names, max_exponent=MAX_EXPONENT)
    if not isinstance(expr, sympy.Expr):
        raise ExpressionError("not an expression")
    return expr


def answer_expr(spec: dict[str, Any], values: dict[str, Value]) -> Any:
    """The answer with this student's params/derived substituted in."""
    names: dict[str, Any] = {k: sympy.sympify(v) for k, v in values.items()}
    names.update({v: sympy.Symbol(v) for v in spec["variables"]})
    return params.parse(spec["value"], names)


def answer_text(spec: dict[str, Any], values: dict[str, Value]) -> str:
    """A plain-text form of the answer that `parse_student` reads back (tests use it)."""
    return str(answer_expr(spec, values))


# --- the time-limited SymPy work ------------------------------------------------------------------


def _warm() -> bool:
    return bool(sympy.simplify(sympy.Symbol("x") - sympy.Symbol("x")) == 0)


def _is_zero(diff: Any) -> bool:
    return bool(sympy.simplify(diff) == 0)


def _ops(student: Any, answer: Any) -> tuple[int, int]:
    return int(sympy.count_ops(student)), int(sympy.count_ops(sympy.simplify(answer)))


class _Limiter:
    """A lazily started process pool; terminated (killing stuck workers) on a timeout."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pool: Pool | None = None

    def _get(self) -> Pool:
        with self._lock:
            if self._pool is None:
                pool = multiprocessing.get_context("spawn").Pool(processes=2)
                # Importing SymPy in a fresh process takes a while; don't count it in the budget.
                pool.apply_async(_warm).get(WARMUP_S)
                self._pool = pool
            return self._pool

    def _reset(self, pool: Pool) -> None:
        with self._lock:
            if self._pool is pool:
                self._pool = None
        pool.terminate()

    def run[T](self, fn: Callable[..., T], *args: Any) -> T | None:
        """`fn(*args)` in a worker; None if it took longer than the time limit."""
        pool = self._get()
        try:
            return pool.apply_async(fn, args).get(TIME_LIMIT_S)
        except multiprocessing.TimeoutError:
            log.warning("expression check timed out; restarting the grading pool")
            self._reset(pool)
            return None

    def close(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.terminate()


_limiter = _Limiter()
atexit.register(_limiter.close)


def _numeric_equal(a: Any, b: Any, variables: list[str]) -> bool:
    """`a == b` at random points (fallback when simplify runs out of time)."""
    symbols = [sympy.Symbol(v) for v in variables]
    rng = random.Random(0)
    fa = sympy.lambdify(symbols, a, "math")
    fb = sympy.lambdify(symbols, b, "math")
    for _ in range(NUMERIC_POINTS * max(1, len(symbols))):
        point = [rng.uniform(-10, 10) for _ in symbols]
        try:
            x, y = complex(fa(*point)), complex(fb(*point))
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        if abs(x - y) > NUMERIC_TOL * max(1.0, abs(y)):
            return False
    return True


def _equivalent(student: Any, answer: Any, variables: list[str]) -> bool:
    zero = _limiter.run(_is_zero, student - answer)
    if zero is None:
        return _numeric_equal(student, answer, variables)
    return zero


@dataclass(frozen=True)
class ExpressionGrade:
    correct: bool
    display_answer: str  # LaTeX
    note: str | None


def grade_expression(
    spec: dict[str, Any], values: dict[str, Value], response: str
) -> ExpressionGrade:
    answer = answer_expr(spec, values)
    display = sympy.latex(answer)
    variables = list(spec["variables"])
    try:
        student = parse_student(response, variables)
    except ExpressionError:
        return ExpressionGrade(False, display, NOTE_UNREADABLE)
    mode = spec["sympy_mode"]
    if mode == "exact":
        return ExpressionGrade(bool(student == answer), display, None)
    if not _equivalent(student, answer, variables):
        return ExpressionGrade(False, display, None)
    if mode == "simplified":
        ops = _limiter.run(_ops, student, answer)
        if ops is None:
            return ExpressionGrade(False, display, NOTE_UNREADABLE)
        if ops[0] > ops[1]:
            return ExpressionGrade(False, display, NOTE_SIMPLIFY)
    return ExpressionGrade(True, display, None)
