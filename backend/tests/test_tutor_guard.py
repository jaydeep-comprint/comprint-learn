"""The tutor's answer guard (spec 009), offline: numbers, expressions, MCQ, code, length."""

import re
from decimal import Decimal

import pytest
import sympy

from app.ai.guard import (
    ExpressionFact,
    GuardFacts,
    NumberFact,
    check,
    expression_spans,
    matches,
    numbers_in,
)


def before(reply: str, facts: GuardFacts, *, draft: str | None = None, limit: int = 80) -> set[str]:
    return {leak.kind for leak in check(reply, facts, mode="before", word_limit=limit, draft=draft)}


def numeric(value: str, mode: str = "exact", **kw: object) -> GuardFacts:
    return GuardFacts(
        numbers=[NumberFact(Decimal(value), mode, **kw)],  # type: ignore[arg-type]
        exempt_texts=["A car covers 120 m in 8 s. Find its speed."],
        stem="A car covers 120 m in 8 s. Find its speed.",
    )


# --- numbers --------------------------------------------------------------------------------------


def test_numbers_in_reads_every_form() -> None:
    found = numbers_in(
        "12, 3/4, 2.5e3, 1.2 \N{MULTIPLICATION SIGN} 10^4, 6 x 10^-2, \\frac{3}{8}, "
        "\N{MINUS SIGN}7, 1,000; x2 is a name"
    )
    for v in ["12", "0.75", "2500", "12000", "0.06", "0.375", "-7", "1000"]:
        assert Decimal(v) in found, v
    assert Decimal(2) not in found  # "x2" is a variable name, not a number


@pytest.mark.parametrize(
    "reply", ["The speed is 15.", "It's 15 m/s", "maybe 15.0?", "30/2", "\\frac{30}{2}", "1.5e1"]
)
def test_answer_number_leaks(reply: str) -> None:
    assert before(reply, numeric("15")) == {"number"}


def test_prompt_numbers_are_exempt() -> None:
    assert before("Look at the 120 m and the 8 s.", numeric("15")) == set()


def test_a_stuffed_draft_exempts_nothing() -> None:
    """Spec 015 review: listing candidate values in the draft can't switch the guard off."""
    stuffed = " ".join(str(i) for i in range(1, 60))
    assert "number" in before("Of those, 15 is the one.", numeric("15"), draft=stuffed)
    long_text = "my working: " + "x" * 80 + " 15"
    assert "number" in before("You wrote 15.", numeric("15"), draft=long_text)


def test_draft_numbers_are_exempt() -> None:
    assert (
        before("You wrote 15 in your draft; check the units.", numeric("15"), draft="15") == set()
    )


def test_derived_values_are_leaks() -> None:
    facts = numeric("15")
    facts.numbers.append(NumberFact(Decimal("4.5")))  # an intermediate result
    assert before("First you get 4.5.", facts) == {"number"}


def test_si_variant_is_a_leak() -> None:
    facts = numeric("54", "exact")  # 54 km/h ...
    facts.numbers.append(NumberFact(Decimal(15)))  # ... = 15 m/s
    assert before("That's 15 metres per second.", facts) == {"number"}


def test_match_bands() -> None:
    assert matches(Decimal("12.04"), NumberFact(Decimal("12"), "exact"))  # within 0.5 %
    assert not matches(Decimal("12.1"), NumberFact(Decimal("12"), "exact"))
    assert matches(Decimal("13"), NumberFact(Decimal("12.5"), "sigfig", 2))  # both round to 13
    assert matches(Decimal("10.4"), NumberFact(Decimal("10"), "tolerance", rel_tol=Decimal("0.05")))
    assert matches(Decimal("-12"), NumberFact(Decimal("12")))  # the sign doesn't hide it
    assert matches(Decimal(0), NumberFact(Decimal(0)))
    assert not matches(Decimal("0.001"), NumberFact(Decimal(0)))


def test_scientific_answer() -> None:
    facts = GuardFacts(numbers=[NumberFact(Decimal("3.0E8"), "sigfig", 2)])
    assert before("about 3 \N{MULTIPLICATION SIGN} 10^8", facts) == {"number"}
    assert before("about 3e8", facts) == {"number"}


# --- expressions ----------------------------------------------------------------------------------


def expr_facts() -> GuardFacts:
    x = sympy.Symbol("x")
    return GuardFacts(
        expressions=[ExpressionFact(2 * x + 6, ("x",))],
        variables=("x",),
        exempt_texts=["Expand 2(x + 3)."],
    )


@pytest.mark.parametrize(
    "reply",
    ["It is 2x + 6.", "so $(x+3) \\cdot 2$ hmm", "try `6 + 2*x`", "y = 2x+6", "$\\frac{4x+12}{2}$"],
)
def test_equivalent_expressions_leak(reply: str) -> None:
    assert before(reply, expr_facts()) == {"expression"}


def test_prompt_expression_and_other_expressions_pass() -> None:
    assert before("Look at $2(x+3)$ again.", expr_facts()) == set()  # in the prompt
    assert before("The question asks you to expand 2(x + 3).", expr_facts()) == set()
    assert before("What does x + 3 mean when x is a number?", expr_facts()) == set()


def test_expression_spans_are_capped() -> None:
    reply = " ".join(f"$x+{i}$" for i in range(10))
    assert len(expression_spans(reply, ["x"])) == 5


# --- MCQ ------------------------------------------------------------------------------------------


def mcq_facts() -> GuardFacts:
    stem = "Which quantity has direction?"
    return GuardFacts(
        options=["Displacement", "Distance travelled", "Speed of the car"],
        stem=stem,
        exempt_texts=[stem],
    )


@pytest.mark.parametrize(
    "reply",
    ["Look at option 2.", "Think about (b).", "The second one is worth a look.", "choice c"],
)
def test_option_references_leak(reply: str) -> None:
    assert "mcq" in before(reply, mcq_facts())


def test_option_text_overlap_leaks() -> None:
    assert "mcq" in before("Think about displacement here.", mcq_facts())
    assert before("What does 'direction' mean for a quantity?", mcq_facts()) == set()


# --- code -----------------------------------------------------------------------------------------

SOLUTION = "def area(w, h):\n    area_total = w * h\n    return area_total\n"


def code_facts() -> GuardFacts:
    starter = "def area(w, h):\n    pass\n"
    return GuardFacts(solution=SOLUTION, starter=starter, exempt_texts=[starter])


def test_multi_line_code_block_leaks() -> None:
    assert before("Try:\n```python\nx = 1\nprint(x)\n```", code_facts()) == {"code"}
    assert before("Try:\n    x = 1\n    print(x)\n", code_facts()) == {"code"}


def test_one_line_code_is_fine() -> None:
    assert before("Add `print(w, h)` to see the inputs.", code_facts()) == set()


def test_solution_line_leaks_unless_in_the_draft() -> None:
    reply = "Write `area_total = w * h` there."
    assert before(reply, code_facts()) == {"code"}
    assert before(reply, code_facts(), draft="def area(w, h):\n    area_total = w * h\n") == set()


def test_after_mode_checks_code_only_when_solution_not_shown() -> None:
    reply = "The fix was area_total = w * h, then return it."
    facts = code_facts()
    hidden = check(reply, facts, mode="after", word_limit=120, solution_shown=False)
    shown = check(reply, facts, mode="after", word_limit=120, solution_shown=True)
    assert [leak.kind for leak in hidden] == ["code"]
    assert shown == []


def test_after_mode_allows_the_answer() -> None:
    assert check("The answer was 15 m/s.", numeric("15"), mode="after", word_limit=120) == []


# --- length ---------------------------------------------------------------------------------------


def test_length_limits() -> None:
    facts = GuardFacts()
    assert before("word " * 100, facts) == set()  # over 80 but under 1.5x: kept
    assert before("word " * 121, facts) == {"length"}
    assert before("Do this:\n1. read it\n2. solve it", facts) == {"length"}
    assert before("- first\n- second", facts) == {"length"}


@pytest.mark.parametrize(
    "draft", ["2x^2 - 7x + 3", "2*x**2 + 3*x - 5", "3/4 + 1/2", "v = 5 + 2*3 = 11"]
)
def test_an_ordinary_algebra_draft_still_exempts_its_numbers(draft: str) -> None:
    """Spec 015 review: one attempt keeps its exemption (only stuffed drafts lose it)."""
    numbers = sorted(set(re.findall(r"\d+", draft)), key=len)
    value = numbers[-1]
    assert before(f"You wrote {value} in your working.", numeric(value), draft=draft) == set()
