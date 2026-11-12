"""The tutor's answer guard (spec 009): deterministic leak checks on every reply. Pure.

`check(reply, facts, ...)` knows the real answer (`GuardFacts`, built on the server from
`item.answer` + the seed and never sent to the model) and returns what leaked: an answer or
derived number, an expression equivalent to the answer, a reference to an MCQ option, solution
code or a multi-line code block, or a reply that is too long / a list of steps. Steps leaked in
words can't be caught here; the prompt, length limits and the eval's judge cover them.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Literal

from app.ai import limits
from app.content.params import ExpressionError
from app.grading.expression import numeric_equal, parse_student
from app.grading.numeric import round_sig

LeakKind = Literal["number", "expression", "mcq", "code", "length"]
REL_BAND = Decimal("0.005")  # 0.5 % relative


@dataclass(frozen=True)
class Leak:
    kind: LeakKind
    detail: str  # for logs/tests: never shown to the model


@dataclass(frozen=True)
class NumberFact:
    """A value the tutor must not state, with the band it's matched in."""

    value: Decimal
    mode: Literal["exact", "sigfig", "tolerance"] = "exact"
    sigfigs: int | None = None
    rel_tol: Decimal | None = None
    abs_tol: Decimal | None = None


@dataclass(frozen=True)
class ExpressionFact:
    expr: Any  # sympy expression with the item's variables as symbols
    variables: tuple[str, ...]


@dataclass
class GuardFacts:
    numbers: list[NumberFact] = field(default_factory=list)
    expressions: list[ExpressionFact] = field(default_factory=list)
    variables: tuple[str, ...] = ()
    options: list[str] = field(default_factory=list)  # MCQ option texts (item or unanswered steps)
    stem: str = ""  # the MCQ stem / prompt text options are compared against
    solution: str | None = None  # code solution
    starter: str = ""
    exempt_texts: list[str] = field(default_factory=list)  # prompt, steps, tests, shown answers


# --- numbers --------------------------------------------------------------------------------------

_EXP = r"(?:\s*[eE][+-]?\d+|\s*(?:\u00d7|x|X|\*|\\times|\\cdot)\s*10\s*\^\s*\{?\s*[+\-]?\d+\s*\}?)"
_NUM = re.compile(
    r"(?<![\w.])(?P<sign>-)?(?P<a>\d+(?:\.\d+)?|\.\d+)(?P<exp>" + _EXP + r")?"
    r"(?:\s*/\s*(?P<b>\d+(?:\.\d+)?))?(?![\w.]*\d)"
)
_FRAC = re.compile(r"\\[dt]?frac\s*\{\s*(-?\d+(?:\.\d+)?)\s*\}\s*\{\s*(-?\d+(?:\.\d+)?)\s*\}")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def _exponent(text: str) -> int:
    digits = re.search(r"[+\-]?\d+\s*\}?\s*$", text)
    assert digits is not None
    return int(digits.group(0).replace("}", "").strip())


def numbers_in(text: str) -> list[Decimal]:
    """Every number in `text`: integers, decimals, `a/b`, `\\frac{a}{b}`, `1.2e3`, `1.2 x 10^3`
    (also with a times sign). Minus signs are normalised first.
    A fraction yields both its value and its parts (a numerator can be a leak on its own)."""
    text = _THOUSANDS.sub("", text.replace("\N{MINUS SIGN}", "-"))
    out: list[Decimal] = []
    with localcontext() as ctx:
        ctx.prec = 40
        for m in _FRAC.finditer(text):
            a, b = Decimal(m.group(1)), Decimal(m.group(2))
            out += [a, b] + ([a / b] if b != 0 else [])
        for m in _NUM.finditer(_FRAC.sub(" ", text)):
            try:
                a = Decimal(m.group("a"))
            except InvalidOperation:
                continue
            if m.group("exp"):
                n = _exponent(m.group("exp"))
                if abs(n) > 300:
                    continue
                a = a.scaleb(n)
            if m.group("sign"):
                a = -a
            out.append(a)
            if m.group("b"):
                b = Decimal(m.group("b"))
                out.append(b)
                if b != 0:
                    out.append(a / b)
    return out


def _close(x: Decimal, v: Decimal, rel: Decimal) -> bool:
    if v == 0:
        return x == 0
    return abs(x - v) <= rel * abs(v)


def matches(x: Decimal, fact: NumberFact) -> bool:
    """`x` (sign ignored) states `fact` within its band (spec 009, "Match band")."""
    x, v = abs(x), abs(fact.value)
    with localcontext() as ctx:
        ctx.prec = 40
        if fact.mode == "tolerance":
            rel = max(REL_BAND, fact.rel_tol or Decimal(0))
            if fact.abs_tol is not None and abs(x - v) <= fact.abs_tol:
                return True
            return _close(x, v, rel)
        n = fact.sigfigs
        if fact.mode == "sigfig" and n and x != 0 and v != 0 and round_sig(x, n) == round_sig(v, n):
            return True
        return _close(x, v, REL_BAND)


def _number_leaks(reply: str, facts: GuardFacts, exempt: Sequence[Decimal]) -> list[Leak]:
    leaks = []
    exempt_abs = {abs(e) for e in exempt}
    for x in numbers_in(reply):
        if abs(x) in exempt_abs:
            continue
        for fact in facts.numbers:
            if matches(x, fact):
                leaks.append(Leak("number", f"{x}"))
                break
    return leaks


# --- expressions ----------------------------------------------------------------------------------

_LATEX = [
    (re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}"), r"((\1)/(\2))"),
    (re.compile(r"\\sqrt\s*\{([^{}]*)\}"), r"sqrt(\1)"),
    (re.compile(r"\\(?:cdot|times)"), "*"),
    (re.compile(r"\\(?:left|right)"), ""),
    (re.compile(r"\\[,;! ]"), " "),
]
_MATH_SPAN = re.compile(r"\$\$?([^$]+)\$\$?|`([^`\n]+)`")
_RUN = re.compile(r"[0-9A-Za-z_+\-*/^().= ]+")
_OPERATOR = re.compile(r"[+\-*/^]|\d\s*[A-Za-z(]|\)\s*[A-Za-z(\d]")
_FUNCTIONS = {"sqrt", "sin", "cos", "tan", "log", "ln", "exp", "abs", "pi"}


def _delatex(text: str) -> str:
    for pattern, repl in _LATEX:
        for _ in range(3):  # nested \frac
            text = pattern.sub(repl, text)
    return text.replace("{", "(").replace("}", ")")


def _trim_words(run: str, variables: set[str]) -> str:
    """Drop English words at the ends of a run ("so it is 2x + 3 then" → "2x + 3")."""
    tokens = run.split()

    def wordy(t: str) -> bool:
        return t.isalpha() and len(t) > 1 and t not in variables and t not in _FUNCTIONS

    while tokens and wordy(tokens[0]):
        tokens.pop(0)
    while tokens and wordy(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def expression_spans(reply: str, variables: Sequence[str]) -> list[str]:
    """Candidate expressions: `$…$`, backticks, and runs with a variable and an operator. Each
    side of an `=` is a separate candidate. At most `MAX_EXPRESSION_SPANS`."""
    names = set(variables)
    if not names:
        return []
    found: list[str] = []
    for m in _MATH_SPAN.finditer(reply):
        found.append(_delatex(m.group(1) or m.group(2)))
    plain = _MATH_SPAN.sub(" ", reply)
    var_re = re.compile(r"(?<![A-Za-z_])(?:" + "|".join(map(re.escape, names)) + r")(?![A-Za-z_])")
    for m in _RUN.finditer(plain):
        run = _trim_words(m.group(0).strip(), names)
        if run and var_re.search(run) and _OPERATOR.search(run):
            found.append(run)
    spans: list[str] = []
    for f in found:
        for side in f.split("="):
            side = side.strip().strip(".,;:")
            if side and side not in spans:
                spans.append(side)
    return spans[: limits.MAX_EXPRESSION_SPANS]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _expression_leaks(reply: str, facts: GuardFacts, exempt_text: str) -> list[Leak]:
    if not facts.expressions:
        return []
    variables = list(facts.variables)
    leaks = []
    for span in expression_spans(reply, variables):
        if _squash(span) in exempt_text:
            continue
        try:
            expr = parse_student(span, variables)
        except (ExpressionError, ValueError, TypeError, SyntaxError, RecursionError):
            continue
        for fact in facts.expressions:
            try:
                same = numeric_equal(expr, fact.expr, list(fact.variables))
            except Exception:
                same = False
            if same:
                leaks.append(Leak("expression", span))
                break
    return leaks


# --- MCQ ------------------------------------------------------------------------------------------

_OPTION_REF = re.compile(
    r"\b(?:option|choice|answer)\s*\(?\s*(?:[a-e]|[1-5])\s*\)?(?![\w])"
    r"|(?<![\w$])\(\s*[a-eA-E]\s*\)"
    r"|\b(?:first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+"
    r"(?:one|option|choice|answer)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _mcq_leaks(reply: str, facts: GuardFacts) -> list[Leak]:
    if not facts.options:
        return []
    leaks = []
    m = _OPTION_REF.search(reply)
    if m:
        leaks.append(Leak("mcq", m.group(0)))
    reply_words = set(_words(reply))
    stem = set(_words(facts.stem))
    for option in facts.options:
        own = [w for w in _words(option) if w not in stem]
        if not own:
            continue
        hit = sum(1 for w in own if w in reply_words)
        if hit / len(own) >= 0.6 and (len(own) >= 2 or len(own[0]) >= 3):
            leaks.append(Leak("mcq", option))
    return leaks


# --- code -----------------------------------------------------------------------------------------

_FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|$)", re.DOTALL)
_INDENTED = re.compile(r"(?:^(?: {4}|\t)\S.*\n?){2,}", re.MULTILINE)


def _norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def code_block_leak(reply: str) -> Leak | None:
    for m in _FENCE.finditer(reply):
        if sum(1 for line in m.group(1).splitlines() if line.strip()) > 1:
            return Leak("code", "multi-line code block")
    if _INDENTED.search(reply):
        return Leak("code", "indented code block")
    return None


def _solution_leaks(reply: str, facts: GuardFacts, draft: str | None) -> list[Leak]:
    if not facts.solution:
        return []
    allowed = {_norm_line(x) for x in (facts.starter + "\n" + (draft or "")).splitlines()}
    flat = _norm_line(reply.replace("`", " "))
    leaks = []
    for line in facts.solution.splitlines():
        n = _norm_line(line)
        if len(n) >= 15 and n not in allowed and n in flat:
            leaks.append(Leak("code", n))
    return leaks


# --- length ---------------------------------------------------------------------------------------

_LIST_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S", re.MULTILINE)


def length_leak(reply: str, word_limit: int) -> Leak | None:
    words = len(reply.split())
    if words > limits.OVER_LIMIT * word_limit:
        return Leak("length", f"{words} words")
    if len(_LIST_LINE.findall(reply)) >= 2:
        return Leak("length", "list of steps")
    return None


# --- entry point ----------------------------------------------------------------------------------


DRAFT_MAX_NUMBERS = 3  # "3.2 * 10^5" is three numbers
DRAFT_MAX_CHARS = 60


def _single_attempt(draft: str | None) -> str:
    """The draft, when it reads as one answer attempt; else nothing is exempt."""
    if not draft:
        return ""
    if len(numbers_in(draft)) > DRAFT_MAX_NUMBERS or len(draft.strip()) > DRAFT_MAX_CHARS:
        return ""
    return draft


def check(
    reply: str,
    facts: GuardFacts,
    *,
    mode: Literal["before", "after"],
    word_limit: int,
    draft: str | None = None,
    solution_shown: bool = False,
) -> list[Leak]:
    """What `reply` leaks. Before mode: every check. After mode (the student has seen the answer
    and explanation): the code check only, and only when the solution wasn't shown; plus length."""
    leaks: list[Leak] = []
    length = length_leak(reply, word_limit)
    if length:
        leaks.append(length)
    if mode == "after":
        if facts.solution and not solution_shown:
            block = code_block_leak(reply)
            leaks += [block] if block else []
            leaks += _solution_leaks(reply, facts, draft)
        return leaks
    # A draft only exempts what it says when it looks like one attempt: a draft stuffed with
    # candidate values ("1 2 3 ... 500, which is right?") must not switch the guard off
    # (spec 015 review, decision 8). Code items keep their line-based draft exemption below.
    own = _single_attempt(draft)
    exempt_texts: Iterable[str] = [*facts.exempt_texts, own]
    exempt_numbers = [n for t in exempt_texts for n in numbers_in(t)]
    leaks += _number_leaks(reply, facts, exempt_numbers)
    leaks += _expression_leaks(reply, facts, _squash(" ".join([*facts.exempt_texts, own])))
    leaks += _mcq_leaks(reply, facts)
    block = code_block_leak(reply)
    leaks += [block] if block else []
    leaks += _solution_leaks(reply, facts, draft)
    return leaks
