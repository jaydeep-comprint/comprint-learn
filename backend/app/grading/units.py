"""Units typed by students (spec 006): aliases, conversion to the authored unit, quantity names.

The parsing itself is `app.content.units.parse_unit` (the same `UNITS` table authors use); this
module only normalises what students type and works out the conversion factor.
"""

import re
from functools import lru_cache

import sympy
from sympy.physics import units as u
from sympy.physics.units.systems.si import SI, dimsys_SI

from app.content.units import UnitError, parse_unit

MAX_UNIT = 40
# Real units use small powers (m^3, s^-2). A bigger one is refused before conversion: SymPy merges
# nested powers, so `((km^999)^999)^999` would otherwise become a billion-digit integer in
# `convert_to` and stall the whole process (it holds the GIL).
MAX_UNIT_POWER = 6

# Whole-token aliases (matching is case-sensitive, so `ms` stays milliseconds).
ALIASES: dict[str, str] = {
    "kmph": "(km/h)",
    "kph": "(km/h)",
    "hr": "h",
    "hrs": "h",
    "mps": "(m/s)",
    "sec": "s",
    "secs": "s",
    "kgs": "kg",
    "Ω": "ohm",
}

_SI_BASE = [u.meter, u.second, u.kilogram, u.ampere, u.kelvin]
_TOKEN = re.compile(r"[A-Za-zΩ]+")
# A space between two operands ("km h^-1", "N m") means multiplication.
_IMPLICIT = re.compile(r"(?<=[A-Za-z0-9)Ω])\s+(?=[A-Za-z(Ω])")

# Dimension (as {base: power}) -> the quantity's name, for "That unit doesn't measure {quantity}".
_QUANTITIES: dict[frozenset[tuple[str, int]], str] = {
    frozenset({("length", 1)}): "length",
    frozenset({("time", 1)}): "time",
    frozenset({("mass", 1)}): "mass",
    frozenset({("length", 1), ("time", -1)}): "speed",
    frozenset({("length", 1), ("time", -2)}): "acceleration",
    frozenset({("mass", 1), ("length", 1), ("time", -2)}): "force",
    frozenset({("mass", 1), ("length", 2), ("time", -2)}): "energy",
    frozenset({("mass", 1), ("length", 2), ("time", -3)}): "power",
    frozenset({("mass", 1), ("length", -1), ("time", -2)}): "pressure",
    frozenset({("time", -1)}): "frequency",
    frozenset({("mass", 1), ("length", 2), ("time", -3), ("current", -1)}): "voltage",
    frozenset({("current", 1)}): "current",
    frozenset({("mass", 1), ("length", 2), ("time", -3), ("current", -2)}): "resistance",
    frozenset({("current", 1), ("time", 1)}): "charge",
    frozenset({("temperature", 1)}): "temperature",
    frozenset({("length", 3)}): "volume",
    frozenset({("mass", 1), ("length", 1), ("time", -1)}): "momentum",
}


def normalise(text: str) -> str:
    """What the student typed → the `parse_unit` syntax (aliases, ², ³, ·, spaces)."""
    out = text.strip().replace("²", "^2").replace("³", "^3").replace("·", "*")
    out = out.replace("⁻¹", "^-1").replace("⁻²", "^-2").replace("\N{MINUS SIGN}", "-")
    out = _IMPLICIT.sub("*", out)
    out = re.sub(r"\s+", "", out)
    return _TOKEN.sub(lambda m: ALIASES.get(m.group(0), m.group(0)), out)


def parse_student_unit(text: str) -> sympy.Expr:
    """Raises `UnitError` for anything that isn't a known unit (or has a power beyond ±6)."""
    if len(text) > MAX_UNIT:
        raise UnitError("unit too long")
    expr = parse_unit(normalise(text))
    for power in expr.atoms(sympy.Pow):
        if abs(power.exp) > MAX_UNIT_POWER:
            raise UnitError("unit power too large")
    return expr


@lru_cache(maxsize=256)
def _authored(text: str) -> sympy.Expr:
    return parse_unit(normalise(text))


def convert_factor(student: str, authored: str) -> sympy.Rational | None:
    """`f` with 1 student unit = f authored units, or None if the dimensions differ.

    Raises `UnitError` if the student's unit can't be read."""
    ratio = parse_student_unit(student) / _authored(authored)
    try:
        converted = sympy.nsimplify(u.convert_to(ratio, _SI_BASE))
    except (ValueError, ArithmeticError, RecursionError) as exc:
        raise UnitError("can't convert that unit") from exc
    if converted.free_symbols or converted.atoms(u.Quantity):
        return None
    if not isinstance(converted, sympy.Rational):
        return None  # every unit in UNITS is a rational multiple of SI
    return converted


def si_factor(authored: str) -> sympy.Rational | None:
    """`f` with 1 authored unit = f SI base units (km → 1000), or None if it can't be worked out.
    Used by the tutor's answer guard (spec 009)."""
    try:
        converted = sympy.nsimplify(u.convert_to(_authored(authored), _SI_BASE))
    except (UnitError, ValueError, ArithmeticError, RecursionError):
        return None
    coeff = converted.as_coeff_Mul()[0]
    return coeff if isinstance(coeff, sympy.Rational) else None


def quantity_name(authored: str) -> str:
    """ "speed", "length", … for the authored unit; "that quantity" if it has no common name."""
    try:
        dim = SI.get_dimensional_expr(_authored(authored))
    except UnitError:
        return "that quantity"
    deps = dimsys_SI.get_dimensional_dependencies(dim)
    key = frozenset((str(d.name), int(p)) for d, p in deps.items())
    return _QUANTITIES.get(key, "that quantity")
