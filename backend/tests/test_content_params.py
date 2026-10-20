import pytest
import sympy

from app.content.params import (
    ExpressionError,
    SampleError,
    evaluate,
    format_number,
    holds,
    parse,
    render,
    sample,
)
from app.content.schema import Item
from app.content.units import UnitError, parse_unit


def _item(**kw: object) -> Item:
    values: dict[str, object] = {
        "id": "q",
        "type": "numeric",
        "bloom": "apply",
        "expected_minutes": 1,
        "prompt": "A car speeds up from {{u}} m/s to {{v}} m/s in {{t}} s.",
        "params": {
            "u": {"min": 0, "max": 10, "step": 2},
            "v": {"min": 12, "max": 30, "step": 2},
            "t": {"choices": [2, 4, 5]},
        },
        "constraints": ["v > u"],
        "derived": {"a": "(v - u) / t"},
        "answer": {"numeric": {"value": "a", "unit": "m/s^2", "mode": "sigfig", "sigfigs": 2}},
    }
    values.update(kw)
    return Item.model_validate(values)


def test_sample_is_deterministic_golden() -> None:
    item = _item()
    first = sample(item, 42)
    assert first == sample(item, 42)
    # Golden values: changing the sampler would change every attempt's numbers (spec 003).
    assert first == {
        "u": sympy.Integer(10),
        "v": sympy.Integer(14),
        "t": sympy.Integer(2),
        "a": sympy.Integer(2),
    }
    assert sample(item, 43) != first


def test_constraints_hold_over_1000_seeds() -> None:
    item = _item(
        params={"u": {"min": 0, "max": 20, "step": 1}, "v": {"min": 0, "max": 20, "step": 1}},
        constraints=["v > u + 3", "v != 10"],
        derived={},
        prompt="{{u}} {{v}}",
        answer={"numeric": {"value": "v - u", "mode": "exact"}},
    )
    for seed in range(1000):
        values = sample(item, seed)
        assert values["v"] > values["u"] + 3


def test_unsatisfiable_constraints_raise() -> None:
    item = _item(constraints=["v < u"])
    with pytest.raises(SampleError):
        sample(item, 1)


def test_decimal_ranges_are_exact() -> None:
    item = _item(
        params={"x": {"min": 0.1, "max": 0.5, "step": 0.1}},
        constraints=[],
        derived={"y": "x * 3"},
        prompt="{{x}}",
    )
    for seed in range(50):
        values = sample(item, seed)
        assert isinstance(values["x"], sympy.Rational)
        assert values["x"] in {sympy.Rational(k, 10) for k in range(1, 6)}
        assert values["y"] == values["x"] * 3


def test_division_by_zero_is_reported() -> None:
    with pytest.raises(ExpressionError, match="finite real"):
        evaluate("1 / (x - 2)", {"x": sympy.Integer(2)})


def test_irrational_values_become_floats() -> None:
    value = evaluate("sqrt(2 * h / g)", {"h": sympy.Integer(20), "g": sympy.Rational("9.8")})
    assert isinstance(value, float)
    assert value == pytest.approx(2.0203, rel=1e-4)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (sympy.Integer(7), "7"),
        (sympy.Integer(-12), "-12"),
        (sympy.Rational(3, 2), "1.5"),
        (sympy.Rational(1, 3), "0.3333"),
        (sympy.Rational(2, 3), "0.6667"),
        (sympy.Rational(8, 4), "2"),
        (12345.6, "12350"),
        (0.000123456, "0.0001235"),
        (2.50, "2.5"),
        (4.0, "4"),
        (9.99995, "10"),
        (0.0, "0"),
    ],
)
def test_format_number(value: sympy.Rational | float, text: str) -> None:
    assert format_number(value) == text


def test_render_substitutes_placeholders() -> None:
    values = {"u": sympy.Integer(2), "a": sympy.Rational(7, 3)}
    assert render("u = {{u}}, a = {{ a }} m/s²", values) == "u = 2, a = 2.333 m/s²"
    with pytest.raises(KeyError):
        render("{{missing}}", values)


def test_constraints_must_be_conditions() -> None:
    assert holds("x > 1 and x < 5", {"x": sympy.Integer(3)})
    assert not holds("not (x > 1)", {"x": sympy.Integer(3)})
    assert holds("1 < x <= 3", {"x": sympy.Integer(3)})
    with pytest.raises(ExpressionError, match="true/false"):
        holds("x + 1", {"x": sympy.Integer(3)})


def test_caret_is_power() -> None:
    assert parse("2^3 / 4", {}) == 2
    assert parse("x^2", {"x": sympy.Symbol("x")}) == sympy.Symbol("x") ** 2


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('true')",
        "x.__class__",
        "().__class__.__bases__[0]",
        "[1, 2][0]",
        "lambda: 1",
        "'abc'",
        "eval('1')",
        "open('/etc/passwd')",
        "Symbol('x')",
        "sqrt(x=1)",
        "2 ** 100000",
        "((9**999)**999)**999",
        "(10**900) * (10**900) ** 10",
        "1" * 40,
        "+".join(["x"] * 150),
        "True",
        "x if x else 1",
        "unknown + 1",
    ],
)
def test_malicious_or_unsupported_expressions_rejected(text: str) -> None:
    with pytest.raises(ExpressionError):
        parse(text, {"x": sympy.Integer(1)})


@pytest.mark.parametrize("text", ["m/s^2", "km/h", "N", "kg*m/s**2", "1/s", "(m/s)/s"])
def test_units_parse(text: str) -> None:
    parse_unit(text)


def test_unit_precedence() -> None:
    from sympy.physics import units as u

    assert parse_unit("m/s^2") == u.meter / u.second**2


@pytest.mark.parametrize(
    "text", ["mps", "m s", "pi", "2", "m^0.5", "sqrt(m)", "m.real", "m + s", "pi*m", "2*m"]
)
def test_bad_units_rejected(text: str) -> None:
    with pytest.raises(UnitError):
        parse_unit(text)
