"""Unit strings in answer specs (`m/s^2`, `km/h`, `N`), parsed with `sympy.physics.units`.

Only the units in `UNITS` are accepted, so a typo (`mps`) is an error rather than a new symbol.
"""

from typing import Any

import sympy
from sympy.physics import units as u

from app.content.params import ExpressionError, parse

UNITS: dict[str, Any] = {
    # length
    "m": u.meter,
    "km": u.kilometer,
    "cm": u.centimeter,
    "mm": u.millimeter,
    # time
    "s": u.second,
    "ms": u.millisecond,
    "min": u.minute,
    "h": u.hour,
    # mass
    "kg": u.kilogram,
    "g": u.gram,
    # mechanics
    "N": u.newton,
    "J": u.joule,
    "kJ": 1000 * u.joule,
    "W": u.watt,
    "kW": 1000 * u.watt,
    "Pa": u.pascal,
    "Hz": u.hertz,
    # electricity (Class 10)
    "V": u.volt,
    "A": u.ampere,
    "ohm": u.ohm,
    "C": u.coulomb,
    # other
    "K": u.kelvin,
    "L": u.liter,
}


class UnitError(ValueError):
    pass


def parse_unit(text: str) -> sympy.Expr:
    """`"m/s^2"` → `meter/second**2`. Products, quotients, integer powers and parentheses only."""
    try:
        expr = parse(text, UNITS, functions={})
    except ExpressionError as exc:
        raise UnitError(f"can't parse unit {text!r}: {exc}") from exc
    if not isinstance(expr, sympy.Expr) or (not expr.free_symbols and not expr.atoms(u.Quantity)):
        raise UnitError(f"{text!r} is not a unit")
    for power in expr.atoms(sympy.Pow):
        if not power.exp.is_integer:
            raise UnitError(f"unit {text!r} has a non-integer power")
    return expr
