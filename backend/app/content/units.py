"""Unit strings in answer specs (`m/s^2`, `km/h`, `N`), parsed with `sympy.physics.units`.

Only the units in `UNITS` are accepted, so a typo (`mps`) is an error rather than a new symbol.
"""

import ast
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


def _shape_problem(text: str) -> str | None:
    """Units are products/quotients of unit names with integer powers: no +, -, numbers or pi."""
    try:
        tree = ast.parse(text.strip().replace("^", "**"), mode="eval")
    except SyntaxError:
        return None  # parse() reports it
    exponents: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow):
            exponents.add(id(n.right))
            if isinstance(n.right, ast.UnaryOp) and isinstance(n.right.op, ast.USub | ast.UAdd):
                exponents.add(id(n.right.operand))  # s^-2
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
            return "units can't be added or subtracted"
        if isinstance(node, ast.Name) and node.id not in UNITS:
            return f"unknown unit {node.id!r}"
        if isinstance(node, ast.Constant) and id(node) not in exponents and node.value != 1:
            return "numbers are only allowed as powers (or 1/...)"
    return None


def parse_unit(text: str) -> sympy.Expr:
    """`"m/s^2"` → `meter/second**2`. Products, quotients, integer powers and parentheses only."""
    if (problem := _shape_problem(text)) is not None:
        raise UnitError(f"can't parse unit {text!r}: {problem}")
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
