"""Numeric answers (spec 005; units since 006).

The student types a number and, when the answer has a unit, a unit of their choice: the answer is
converted into the student's unit (`v' = v / f`) and the mode is applied there. Exact decimal
arithmetic throughout (`Decimal`), so significant figures and rounding are exact.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

import sympy

from app.content import params
from app.content.params import Value
from app.content.units import UnitError
from app.grading import units

NOTE_NOT_A_NUMBER = "Enter a number, e.g. 12.5 or 3.0e8"
NOTE_SCI = "Write it in scientific notation"
NOTE_BAD_UNIT = "Couldn't read that unit"
MAX_EXPONENT = 400
_PRECISION = 60

_NUMBER = re.compile(
    r"""^(?P<sign>[+-]?)\s*
    (?P<mantissa>\d+(?:\.\d*)?|\.\d+)
    (?:
        [eE](?P<e>[+-]?\d+)
      | \s*[\N{MULTIPLICATION SIGN}xX*]\s*10\s*\^\s*\(?(?P<pow>[+-]?\d+)\)?
    )?$""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class Parsed:
    value: Decimal
    mantissa: str  # digits as typed, without sign or exponent
    sci: bool  # written with an exponent


def parse_number(raw: str) -> Parsed | None:
    """The accepted forms: optional sign, digits, optional decimals, optional exponent
    (`e±n`, `E±n`, `10^n` with a times sign, `x10^n`, `*10^n`). A thousands separator `,` is
    rejected."""
    text = raw.strip().replace("\N{MINUS SIGN}", "-")
    m = _NUMBER.match(text)
    if m is None:
        return None
    exp_text = m.group("e") or m.group("pow")
    exponent = int(exp_text) if exp_text is not None else 0
    if abs(exponent) > MAX_EXPONENT:
        return None
    mantissa = m.group("mantissa")
    value = Decimal(mantissa).scaleb(exponent)
    if m.group("sign") == "-":
        value = -value
    return Parsed(value=value, mantissa=mantissa, sci=exp_text is not None)


def sig_fig_range(mantissa: str) -> tuple[int, int]:
    """(fewest, most) significant figures the typed digits can have.

    Leading zeros never count; trailing zeros after a decimal point do. An integer's trailing
    zeros are ambiguous (`270` has 2 or 3)."""
    if "." in mantissa:
        digits = mantissa.replace(".", "").lstrip("0")
        return len(digits), len(digits)
    digits = mantissa.lstrip("0")
    if not digits:
        return 0, 0
    return len(digits.rstrip("0")), len(digits)


def to_decimal(x: Value) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        if isinstance(x, sympy.Rational):
            return Decimal(int(x.p)) / Decimal(int(x.q))
        return Decimal(float(x))


def round_sig(x: Decimal, n: int) -> Decimal:
    """`x` rounded half-up to `n` significant figures, keeping the trailing zeros."""
    if x == 0:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return x.quantize(Decimal(1).scaleb(x.adjusted() - n + 1), rounding=ROUND_HALF_UP)


def _plain(d: Decimal) -> str:
    out = format(d, "f")
    return out.lstrip("-") if d == 0 else out


def _sci(d: Decimal, n: int | None) -> str:
    """`a x 10^n` (times sign) with 1 <= |a| < 10 (`n` significant figures if given)."""
    if d == 0:
        return "0"
    exponent = d.adjusted()
    mantissa = d.scaleb(-exponent)
    mantissa = round_sig(mantissa, n) if n is not None else mantissa.normalize()
    return f"{_plain(mantissa)}\N{MULTIPLICATION SIGN}10^{exponent}"


def _with_unit(text: str, unit: str | None) -> str:
    return f"{text} {unit}" if unit else text


def _display(spec: dict[str, Any], v: Decimal) -> str:
    mode = spec["mode"]
    sci = bool(spec.get("sci_notation"))
    if mode == "sigfig":
        n = int(spec["sigfigs"])
        return _sci(round_sig(v, n), n) if sci else _plain(round_sig(v, n))
    if mode == "exact":
        return _sci(v, None) if sci else _plain(v.normalize() if v != 0 else Decimal(0))
    # tolerance: the fewest significant figures that are still within the tolerance
    for n in range(3, 16):
        r = round_sig(v, n)
        if _within(spec, r, v):
            return _sci(r, n) if sci else _plain(r)
    return _plain(v)


def _within(spec: dict[str, Any], x: Decimal, v: Decimal) -> bool:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        diff = abs(x - v)
        rel = spec.get("rel_tol")
        if rel is not None and diff <= Decimal(str(rel)) * abs(v):
            return True
        absolute = spec.get("abs_tol")
        return absolute is not None and diff <= Decimal(str(absolute))


def is_sci_form(p: Parsed) -> bool:
    if not p.sci:
        return False
    a = Decimal(p.mantissa)
    return a == 0 or 1 <= a < 10


def _right_value_other_count(x: Decimal, v: Decimal, lo: int, hi: int) -> bool:
    """Is `x` the answer rounded to the s.f. count the student actually gave?"""
    return any(n > 0 and x == round_sig(v, n) for n in {lo, hi})


@dataclass(frozen=True)
class NumericGrade:
    correct: bool
    display_answer: str
    note: str | None


def _finite_decimal(r: sympy.Rational) -> bool:
    q = int(r.q)
    for p in (2, 5):
        while q % p == 0:
            q //= p
    return q == 1


def _judge(spec: dict[str, Any], parsed: Parsed, v: Decimal) -> tuple[bool, str | None]:
    x = parsed.value
    mode = spec["mode"]
    note: str | None = None
    if mode == "exact":
        correct = x == v
    elif mode == "sigfig":
        n = int(spec["sigfigs"])
        lo, hi = sig_fig_range(parsed.mantissa)
        right_count = lo <= n <= hi
        correct = right_count and x == round_sig(v, n)
        if not correct and not right_count and _right_value_other_count(x, v, lo, hi):
            note = f"Give {n} significant figures"
    else:
        correct = _within(spec, x, v)
    if correct and spec.get("sci_notation") and not is_sci_form(parsed):
        return False, NOTE_SCI
    return correct, note


def grade_numeric(
    spec: dict[str, Any], values: dict[str, Value], response: str, unit: str | None = None
) -> NumericGrade:
    """`unit` is what the student typed in the unit box (only for answers with a unit)."""
    value = params.evaluate(spec["value"], values)
    v = to_decimal(value)
    authored = spec.get("unit")
    display = _with_unit(_display(spec, v), authored)
    parsed = parse_number(response)
    if parsed is None:
        return NumericGrade(False, display, NOTE_NOT_A_NUMBER)
    if authored:
        if unit is None or not unit.strip():
            return NumericGrade(False, display, f"Add a unit, e.g. {authored}")
        try:
            f = units.convert_factor(unit, authored)
        except UnitError:
            return NumericGrade(False, display, NOTE_BAD_UNIT)
        if f is None:
            quantity = units.quantity_name(authored)
            return NumericGrade(False, display, f"That unit doesn't measure {quantity}")
        if f != 1:
            if isinstance(value, sympy.Rational):
                converted = value / f
                if spec["mode"] == "exact" and not _finite_decimal(converted):
                    return NumericGrade(False, display, f"Give it in {authored}")
                v = to_decimal(converted)
            else:
                with localcontext() as ctx:
                    ctx.prec = _PRECISION
                    v = v / to_decimal(f)
    correct, note = _judge(spec, parsed, v)
    return NumericGrade(correct, display, note)
