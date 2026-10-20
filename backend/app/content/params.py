"""Randomised numbers: safe expression parsing, deterministic sampling and prompt rendering.

`sample(item, seed)` is the single implementation later specs use to derive an item's numbers
(and so its answer) from an attempt's seed. Expressions are never `eval`ed: a whitelisted Python
`ast` walk builds SymPy objects directly, so names, calls and operators outside it are rejected.
"""

import ast
import math
import random
import re
from collections.abc import Callable, Mapping
from typing import Any

import sympy

from app.content.schema import Item, RangeOrChoices

MAX_DRAWS = 100
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# A sampled number: exact `sympy.Rational` when possible, else `float`.
type Value = Any

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sqrt": sympy.sqrt,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "exp": sympy.exp,
    "log": sympy.log,
    "ln": sympy.log,
    "abs": sympy.Abs,
    "floor": sympy.floor,
    "ceiling": sympy.ceiling,
    "Min": sympy.Min,
    "Max": sympy.Max,
}
CONSTANTS: dict[str, sympy.Expr] = {"pi": sympy.pi, "E": sympy.E}
RESERVED = frozenset(FUNCTIONS) | frozenset(CONSTANTS)

# Bounds so a short input can't stall the process on bignum work (later specs may parse
# student input with this): exponent size, result size, literal size and AST size.
MAX_EXPONENT = 1000
MAX_RESULT_BITS = 10_000
MAX_LITERAL_DIGITS = 30
MAX_NODES = 200


def _pow(base: Any, exponent: Any) -> Any:
    if getattr(exponent, "is_number", False):
        if abs(exponent) > MAX_EXPONENT:
            raise ExpressionError(f"exponents above {MAX_EXPONENT} aren't allowed")
        if getattr(base, "is_number", False) and base != 0:
            bits = abs(float(sympy.log(abs(base), 2).evalf(15))) * abs(float(exponent))
            if bits > MAX_RESULT_BITS:
                raise ExpressionError("that power is too large")
    return base**exponent


_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: _pow,
    ast.Mod: lambda a, b: sympy.Mod(a, b),
}
_COMPARE: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Lt: sympy.Lt,
    ast.LtE: sympy.Le,
    ast.Gt: sympy.Gt,
    ast.GtE: sympy.Ge,
    ast.Eq: sympy.Eq,
    ast.NotEq: sympy.Ne,
}


class ExpressionError(ValueError):
    pass


class SampleError(ValueError):
    pass


def parse(
    text: str | int | float,
    names: Mapping[str, Any],
    *,
    functions: Mapping[str, Callable[..., Any]] = FUNCTIONS,
) -> Any:
    """Parses `text` into a SymPy object; names resolve only via `names`, `functions`, constants."""
    if isinstance(text, bool):
        raise ExpressionError("expected a number or an expression")
    if isinstance(text, int | float):
        return _number(text)
    if len(text) > 500:
        raise ExpressionError("expression is too long")
    try:
        # Authors write x^2; Python's ^ binds looser than /, so rewrite it before parsing.
        tree = ast.parse(text.strip().replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"can't parse {text!r}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ExpressionError("expression is too long")
    try:
        return _Walker(names, functions).visit(tree.body)
    except (RecursionError, MemoryError) as exc:
        raise ExpressionError(f"can't evaluate {text!r}: too complex") from exc
    except (TypeError, ValueError, ZeroDivisionError, AttributeError) as exc:
        if isinstance(exc, ExpressionError):
            raise
        raise ExpressionError(f"can't evaluate {text!r}: {exc}") from exc


def _number(n: int | float) -> sympy.Rational:
    if isinstance(n, float) and not math.isfinite(n):
        raise ExpressionError("numbers must be finite")
    # Through str so 0.1 is exactly 1/10, not the nearest binary float.
    return sympy.Rational(str(n))


class _Walker:
    def __init__(
        self, names: Mapping[str, Any], functions: Mapping[str, Callable[..., Any]]
    ) -> None:
        self.names = names
        self.functions = functions

    def visit(self, node: ast.AST) -> Any:
        match node:
            case ast.Constant(value=bool()):
                raise ExpressionError("True/False aren't allowed")
            case ast.Constant(value=int() | float() as n):
                if len(str(n)) > MAX_LITERAL_DIGITS:
                    raise ExpressionError("numbers can have at most 30 digits")
                return _number(n)
            case ast.Name(id=name):
                if name in self.names:
                    return self.names[name]
                if name in CONSTANTS:
                    return CONSTANTS[name]
                raise ExpressionError(f"unknown name {name!r}")
            case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINOPS:
                return _BINOPS[type(op)](self.visit(left), self.visit(right))
            case ast.UnaryOp(op=ast.USub(), operand=operand):
                return -self.visit(operand)
            case ast.UnaryOp(op=ast.UAdd(), operand=operand):
                return self.visit(operand)
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                return sympy.Not(self.visit(operand))
            case ast.BoolOp(op=op, values=values):
                parts = [self.visit(v) for v in values]
                return sympy.And(*parts) if isinstance(op, ast.And) else sympy.Or(*parts)
            case ast.Compare(left=left, ops=ops, comparators=comparators):
                terms = [self.visit(left), *(self.visit(c) for c in comparators)]
                pairs = []
                for i, cmp in enumerate(ops):
                    if type(cmp) not in _COMPARE:
                        raise ExpressionError(f"operator {type(cmp).__name__} isn't allowed")
                    pairs.append(_COMPARE[type(cmp)](terms[i], terms[i + 1]))
                return sympy.And(*pairs)
            case ast.Call(func=ast.Name(id=fname), args=args, keywords=[]) if (
                fname in self.functions
            ):
                return self.functions[fname](*(self.visit(a) for a in args))
            case ast.Call():
                raise ExpressionError(
                    "only whitelisted functions can be called (sqrt, sin, log, ...)"
                )
            case _:
                raise ExpressionError(f"{type(node).__name__} isn't allowed in expressions")


# --- sampling -------------------------------------------------------------------------------------


def param_values(spec: RangeOrChoices) -> list[sympy.Rational]:
    """Every value a param can take, in order."""
    if spec.choices is not None:
        return [_number(c) for c in spec.choices]
    assert spec.min is not None and spec.max is not None and spec.step is not None
    lo, hi, step = _number(spec.min), _number(spec.max), _number(spec.step)
    count = int(sympy.floor((hi - lo) / step)) + 1
    if count > 100_000:
        raise ExpressionError("range has too many values (more than 100,000)")
    return [lo + k * step for k in range(count)]


def to_value(x: Any) -> Value:
    """A finite real value: exact `Rational` if possible, else `float`. Raises `ExpressionError`."""
    x = sympy.sympify(x)
    if isinstance(x, sympy.Rational):
        return x
    if not (getattr(x, "is_number", False) and x.is_real and x.is_finite):
        raise ExpressionError("is not a finite real number (division by zero?)")
    return float(x.evalf(17))


def evaluate(text: str | int | float, values: Mapping[str, Value]) -> Value:
    return to_value(parse(text, {k: sympy.sympify(v) for k, v in values.items()}))


def holds(constraint: str, values: Mapping[str, Value]) -> bool:
    result = parse(constraint, {k: sympy.sympify(v) for k, v in values.items()})
    if result is sympy.true:
        return True
    if result is sympy.false:
        return False
    raise ExpressionError(f"constraint {constraint!r} is not a true/false condition")


def sample(item: Item, seed: int) -> dict[str, Value]:
    """Params drawn in declaration order (retried until `constraints` hold), then `derived`.

    Deterministic for a given item and seed. Raises `SampleError` if no draw satisfies the
    constraints and `ExpressionError` if a derived value isn't a finite real number.
    """
    rng = random.Random(seed)
    pools = {name: param_values(spec) for name, spec in item.params.items()}
    for _ in range(MAX_DRAWS):
        values: dict[str, Value] = {name: rng.choice(pool) for name, pool in pools.items()}
        if all(holds(c, values) for c in item.constraints):
            break
    else:
        raise SampleError(f"no values satisfied the constraints in {MAX_DRAWS} draws")
    for name, expr in item.derived.items():
        try:
            values[name] = evaluate(expr, values)
        except ExpressionError as exc:
            raise ExpressionError(f"derived {name} {exc}") from exc
    return values


# --- rendering ------------------------------------------------------------------------------------


def format_number(x: Value) -> str:
    """Integers print plainly; anything else with up to 4 significant figures, no trailing zeros."""
    if isinstance(x, sympy.Rational) and x.q == 1:
        return str(x.p)
    f = float(x)
    if f.is_integer() and abs(f) < 1e15:
        return str(int(f))
    if f == 0:
        return "0"
    exponent = math.floor(math.log10(abs(f)))
    decimals = 3 - exponent
    rounded = round(f, decimals)
    if decimals <= 0:
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")


def placeholders(template: str) -> list[str]:
    return PLACEHOLDER.findall(template)


def render(template: str, values: Mapping[str, Value]) -> str:
    """Replaces `{{name}}` with `format_number(values[name])`; `KeyError` for an unknown name."""
    return PLACEHOLDER.sub(lambda m: format_number(values[m.group(1)]), template)
