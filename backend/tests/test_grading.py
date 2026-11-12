"""Server-side grading (spec 005): numeric, expression and MCQ. Pure, no DB."""

import itertools
from typing import Any

import pytest
import sympy

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.hashing import split_item
from app.content.loader import load
from app.content.params import sample
from app.grading import QUICK_TYPES, InvalidOptionError, ShownOptions, grade
from app.grading.expression import answer_text, preprocess
from app.grading.numeric import parse_number, sig_fig_range
from app.schemas.content import OptionPublic

R = sympy.Rational


def num(spec: dict[str, Any], response: str, values: dict[str, Any] | None = None) -> Any:
    """Answers in the authored unit (unit conversion: test_grading_units.py)."""
    return grade("numeric", {"spec": spec}, values or {}, response, unit=spec.get("unit"))


def expr(spec: dict[str, Any], response: str, values: dict[str, Any] | None = None) -> Any:
    return grade("expression", {"spec": spec}, values or {}, response)


# --- numeric --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("8", "8"),
        ("-8.50", "-8.50"),
        (" .5 ", "0.5"),
        ("3.0e8", "3.0e8"),
        ("3.0E-8", "3.0e-8"),
        ("3.0\N{MULTIPLICATION SIGN}10^8", "3.0e8"),
        ("3.0 x 10^-8", "3.0e-8"),
        ("3*10^8", "3e8"),
        ("\N{MINUS SIGN}2", "-2"),
    ],
)
def test_parse_number_accepts(raw: str, value: str) -> None:
    parsed = parse_number(raw)
    assert parsed is not None
    assert parsed.value == __import__("decimal").Decimal(value)


@pytest.mark.parametrize("raw", ["12,5", "abc", "1.2.3", "", "e8", "1e", "1/2", "1e9999"])
def test_parse_number_rejects(raw: str) -> None:
    assert parse_number(raw) is None


def test_sig_fig_range() -> None:
    assert sig_fig_range("26.7") == (3, 3)
    assert sig_fig_range("0.0040") == (2, 2)
    assert sig_fig_range("270") == (2, 3)
    assert sig_fig_range("30.0") == (3, 3)
    assert sig_fig_range("1000") == (1, 4)
    assert sig_fig_range("0") == (0, 0)


def test_numeric_exact() -> None:
    spec = {"value": "8", "mode": "exact", "unit": "m/s"}
    for ok in ("8", "8.0", "8.00", "+8"):
        assert num(spec, ok).correct
    assert not num(spec, "8.01").correct
    assert num(spec, "8").display_answer == "8 m/s"
    zero = {"value": "0", "mode": "exact"}
    assert num(zero, "-0").correct and num(zero, "0.0").correct


def test_numeric_sigfig_is_strict() -> None:
    spec = {"value": "80/3", "mode": "sigfig", "sigfigs": 3, "unit": "km/h"}
    right = num(spec, "26.7")
    assert right.correct and right.display_answer == "26.7 km/h"
    too_many = num(spec, "26.67")
    assert not too_many.correct and too_many.note == "Give 3 significant figures"
    assert not num(spec, "27").correct
    assert not num(spec, "26.6").correct
    assert num(spec, "26.6").note is None
    assert num({"value": "270", "mode": "sigfig", "sigfigs": 3}, "270").correct
    thirty = {"value": "30", "mode": "sigfig", "sigfigs": 3}
    assert num(thirty, "30.0").correct and not num(thirty, "30").correct
    assert num(thirty, "30").display_answer == "30.0"
    # half-up rounding: 0.125 -> 0.13 to 2 s.f.
    assert num({"value": "1/8", "mode": "sigfig", "sigfigs": 2}, "0.13").correct


def test_numeric_tolerance() -> None:
    rel = {"value": "(x2 - x1) / t", "mode": "tolerance", "rel_tol": 0.02}
    values = {"x1": R(20), "x2": R(-80), "t": R(30)}  # -10/3
    assert num(rel, "-3.33", values).correct
    assert num(rel, "-3.3", values).correct  # within 2%
    assert not num(rel, "-3.2", values).correct
    assert not num(rel, "3.33", values).correct
    absolute = {"value": "9.81", "mode": "tolerance", "abs_tol": 0.05}
    assert num(absolute, "9.8").correct and not num(absolute, "9.7").correct


def test_numeric_sci_notation() -> None:
    spec = {"value": "300000000", "mode": "sigfig", "sigfigs": 2, "sci_notation": True}
    assert num(spec, "3.0e8").correct
    assert num(spec, "3.0\N{MULTIPLICATION SIGN}10^8").correct
    plain = num(spec, "300000000")
    assert not plain.correct
    unnormalised = num(spec, "30e7")
    assert not unnormalised.correct and unnormalised.note == "Write it in scientific notation"
    assert num(spec, "3.0e8").display_answer == "3.0\N{MULTIPLICATION SIGN}10^8"


@pytest.mark.parametrize("raw", ["12,5", "abc", "1 2"])
def test_numeric_bad_input_is_wrong_with_note(raw: str) -> None:
    out = num({"value": "12.5", "mode": "exact"}, raw)
    assert not out.correct
    assert out.note == "Enter a number, e.g. 12.5 or 3.0e8"


# --- expression -----------------------------------------------------------------------------------


def test_preprocess_implicit_multiplication() -> None:
    assert preprocess("2x") == "2*x"
    assert preprocess("3(x+1)") == "3*(x+1)"
    assert preprocess("(x+1)(x-1)") == "(x+1)*(x-1)"
    assert preprocess("(x+1)x") == "(x+1)*x"
    assert preprocess("3x^2 + 2") == "3*x**2 + 2"
    assert preprocess("sqrt(x)") == "sqrt(x)"
    assert preprocess("2sin(x)") == "2*sin(x)"


EQUIV = {"value": "d0 + v*t", "variables": ["t"], "sympy_mode": "equivalent"}
VALUES = {"d0": R(10), "v": R(5)}


def test_expression_equivalent() -> None:
    for ok in ("10 + 5t", "5t+10", "5(t+2)", "5*t + 10", "t*5+10"):
        assert expr(EQUIV, ok, VALUES).correct, ok
    assert not expr(EQUIV, "5t", VALUES).correct
    assert not expr(EQUIV, "d0 + v*t", VALUES).correct  # params aren't names the student may use
    two = {"value": "x*(2*x+3)", "variables": ["x"], "sympy_mode": "equivalent"}
    assert expr(two, "2x^2+3x").correct


def test_expression_exact_and_simplified() -> None:
    exact = {"value": "x*(2*x+3)", "variables": ["x"], "sympy_mode": "exact"}
    assert expr(exact, "x(2x+3)").correct
    assert expr(exact, "(2x+3)x").correct
    assert not expr(exact, "2x^2+3x").correct
    simplified = {"value": "x + 1", "variables": ["x"], "sympy_mode": "simplified"}
    assert expr(simplified, "1 + x").correct
    out = expr(simplified, "(x^2 - 1)/(x - 1)")
    assert not out.correct and out.note == "Simplify your answer"


@pytest.mark.parametrize(
    "raw",
    ["__import__('os')", "().__class__", "x.real", "9**9**9", "x**101", "open('f')", "x" * 201, ""],
)
def test_expression_rejects_unsafe_or_unreadable(raw: str) -> None:
    spec = {"value": "x", "variables": ["x"], "sympy_mode": "equivalent"}
    out = expr(spec, raw)
    assert not out.correct
    assert out.note == "Couldn't read that expression"


def test_expression_display_is_latex() -> None:
    assert expr(EQUIV, "5t", VALUES).display_answer == "5 t + 10"


# --- mcq ------------------------------------------------------------------------------------------


def test_mcq_positional_mapping() -> None:
    shown = ShownOptions([OptionPublic(id=i, text=i.upper()) for i in ("c", "a", "b")])
    answer = {"correct": "a", "misconceptions": {"c": "some-slug"}}
    right = grade("mcq", answer, {}, "2", shown=shown)
    assert right.correct and right.display_answer == "2" and right.chosen == "a"
    wrong = grade("mcq", answer, {}, "1", shown=shown)
    assert not wrong.correct and wrong.misconception == "some-slug" and wrong.display_answer == "2"
    for bad in ("0", "4", "a", "", "\N{FULLWIDTH DIGIT ONE}"):
        with pytest.raises(InvalidOptionError):
            grade("mcq", answer, {}, bad, shown=shown)


# --- every gradable pool item in the sample content ----------------------------------------------


def _pool_items() -> list[Any]:
    bundle = load(DEFAULT_CONTENT_ROOT)
    return [
        pytest.param(item, id=f"{concept.qualified_id}/{item.id}")
        for concept in bundle.concepts
        for kp in concept.file.kps
        for item in kp.items
        if item.type.value in QUICK_TYPES
    ]


@pytest.mark.parametrize("item", _pool_items())
def test_sample_items_accept_their_own_answer(item: Any) -> None:
    public, answer = split_item(item)
    seeds = range(20) if item.has_params else range(1)
    for seed in seeds:
        values = sample(item, seed)
        if item.type.value == "mcq":
            shown = ShownOptions([OptionPublic(**o) for o in public["options"]])
            first = grade("mcq", answer, values, "1", shown=shown)
            assert grade("mcq", answer, values, first.display_answer, shown=shown).correct
            continue
        unit = answer["spec"].get("unit")
        probe = grade(item.type.value, answer, values, "0", unit=unit)
        if item.type.value == "numeric":
            response = probe.display_answer.removesuffix(f" {unit}")
        else:
            response = answer_text(answer["spec"], values)
        result = grade(item.type.value, answer, values, response, unit=unit)
        assert result.correct, (seed, values, response, result)


def test_combinations_of_sigfig_answers_round_trip() -> None:
    for value, n in itertools.product(["1/3", "2/3", "1000/7", "1/700", "123456"], range(1, 7)):
        spec = {"value": value, "mode": "sigfig", "sigfigs": n}
        shown = num(spec, "0").display_answer
        assert num(spec, shown).correct, (value, n, shown)


def test_expression_falls_back_to_numeric_check_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.grading import expression

    monkeypatch.setattr(expression._limiter, "run", lambda *_a: None)
    assert expr(EQUIV, "5(t+2)", VALUES).correct
    assert not expr(EQUIV, "5(t+3)", VALUES).correct


def test_time_limit_is_per_check_and_keeps_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.grading import expression

    assert expression._limiter.run(__import__("time").sleep, 5) is None  # 1 s budget in the worker
    pool = expression._limiter._pool
    assert expression._limiter.run(expression._warm) is True
    assert expression._limiter._pool is pool  # a slow check doesn't restart the pool


def test_numeric_fallback_needs_real_comparisons() -> None:
    from app.grading.expression import _numeric_equal

    x = sympy.Symbol("x")
    assert not _numeric_equal(sympy.log(-1 - x**2), x, ["x"])  # never evaluates: can't tell
    assert _numeric_equal(2 * x + 2, 2 * (x + 1), ["x"])


def test_simplified_accepts_when_out_of_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.grading import expression

    monkeypatch.setattr(expression._limiter, "run", lambda *_a: None)
    simplified = {"value": "x + 1", "variables": ["x"], "sympy_mode": "simplified"}
    assert expr(simplified, "1 + x").correct


@pytest.mark.parametrize(
    "text",
    [
        "(999999999999999999999999999999^100+1)^(1/2)",
        "x^(1/2)+(999999999999999999999999999999^100+1)^(1/3)",
        "sqrt(999999999999999999999999999999^100*999999999999999999999999999999^100"
        "*999999999999999999999999999999^100+7)",
        "(2^1000+1)^(0.5)",
        "(sqrt(2)+999999999999999999999999999999^20)^(1/2)",
    ],
)
def test_roots_of_huge_numbers_are_refused_fast(text: str) -> None:
    """Spec 015 security review (area 5): these stalled the API (factorint) for seconds to
    minutes, holding the GIL. Refused while parsing, well under a second (slow CI runners too)."""
    import time

    from app.content.params import ExpressionError
    from app.grading.expression import parse_student

    started = time.perf_counter()
    with pytest.raises(ExpressionError):
        parse_student(text, ["x"])
    assert time.perf_counter() - started < 0.5


def test_ordinary_roots_still_parse() -> None:
    from app.grading.expression import parse_student

    assert str(parse_student("sqrt(2)", [])) == "sqrt(2)"
    assert str(parse_student("(x^2+1)^(1/2)", ["x"])) == "sqrt(x**2 + 1)"
    assert str(parse_student("27^(1/3)", [])) == "3"
