"""The XP rule (spec 008), pure: `session_xp`, `is_rushed`, streaks and IST weeks. No DB."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.loader import load
from app.models import SessionKind, XpGrade
from app.services.xp import (
    PositionXp,
    competition_ranks,
    day_met,
    is_rushed,
    ist_week_start,
    session_xp,
    streak_from_days,
)

KP, REM, PRACTICE = SessionKind.kp, SessionKind.remediation, SessionKind.practice
SLOW = 60_000  # a real try at a 1-minute item


def p(correct: bool, minutes: str = "1", ms: int = SLOW) -> PositionXp:
    return PositionXp(Decimal(minutes), correct, ms)


def ps(pattern: str, minutes: str = "1", ms: int = SLOW) -> list[PositionXp]:
    return [p(c == "C", minutes, ms) for c in pattern]


@pytest.mark.parametrize(
    ("kind", "outcome", "positions", "amount", "grade"),
    [
        (KP, "passed", ps("CC"), 2, XpGrade.perfect),  # 2 x 1.2 = 2.4
        (KP, "passed", ps("WWCC"), 4, XpGrade.passed),
        (KP, "failed", ps("CWCWW"), 0, XpGrade.poor),  # 2/5 right: below half
        (KP, "failed", ps("CWCWC"), 2, XpGrade.partial),  # 3/5: 5 x 0.3 = 1.5
        (KP, "failed", ps("CWW"), 0, XpGrade.poor),  # 1/3
        (REM, "passed", ps("CCC"), 4, XpGrade.perfect),  # 3.6
        (REM, "failed", [*ps("CC"), *ps("WWW")], 0, XpGrade.poor),  # 2/5
        (REM, "failed", ps("CCWWC"), 2, XpGrade.partial),  # 3/5
        (PRACTICE, "passed", ps("C", "10"), 12, XpGrade.perfect),
        (PRACTICE, "failed", ps("W", "10", 600_000), 0, XpGrade.poor),  # never partial
    ],
)
def test_session_xp_table(
    kind: SessionKind,
    outcome: str,
    positions: list[PositionXp],
    amount: int,
    grade: XpGrade,
) -> None:
    calc = session_xp(kind, outcome, positions)  # type: ignore[arg-type]
    assert (calc.amount, calc.grade) == (amount, grade)
    assert calc.answered == len(positions)
    assert calc.base_minutes == sum(x.expected_minutes for x in positions)


def test_rushed_fail_is_a_small_penalty() -> None:
    fast = [*ps("C"), *ps("WWW", ms=2_000), *ps("C")]  # 3 rushed wrong answers
    calc = session_xp(KP, "failed", fast)
    assert (calc.amount, calc.grade, calc.rushed_count) == (-1, XpGrade.rushed, 3)  # 0.25 x 5
    big = session_xp(KP, "failed", ps("WWW", "4", 2_000))  # 0.25 x 12 = 3
    assert big.amount == -3


def test_rushed_takes_precedence_over_partial() -> None:
    # 3/5 right would be partial, but 2 of the wrong answers were rushed.
    calc = session_xp(KP, "failed", [*ps("CCC"), *ps("WW", ms=1_000)])
    assert calc.grade == XpGrade.rushed


def test_one_rushed_answer_in_a_longer_fail_is_not_rushed() -> None:
    calc = session_xp(KP, "failed", [*ps("CWC"), p(False, ms=1_000), p(True)])
    assert calc.grade == XpGrade.partial


def test_single_rushed_practice_item_costs_one() -> None:
    calc = session_xp(PRACTICE, "failed", [p(False, "2", 3_000)])
    assert (calc.amount, calc.grade) == (-1, XpGrade.rushed)


def test_fast_correct_answers_are_never_penalised() -> None:
    calc = session_xp(KP, "passed", ps("CC", ms=500))
    assert (calc.amount, calc.grade, calc.rushed_count) == (2, XpGrade.perfect, 0)


def test_practice_pass_with_a_wrong_step_is_passed() -> None:
    item = PositionXp(Decimal("5"), True, SLOW, every_step=False)  # 3 of 4 steps, last right
    assert session_xp(PRACTICE, "passed", [item]).grade == XpGrade.passed
    assert session_xp(KP, "passed", [item, item]).grade == XpGrade.perfect  # KPs: item level


def test_practice_pass_after_a_failed_session_is_passed() -> None:
    calc = session_xp(PRACTICE, "passed", ps("C", "10"), first_try=False)
    assert (calc.amount, calc.grade) == (10, XpGrade.passed)


def h(pattern: str, hints: list[int], minutes: str = "1") -> list[PositionXp]:
    return [
        PositionXp(Decimal(minutes), c == "C", SLOW, hints=n)
        for c, n in zip(pattern, hints, strict=True)
    ]


@pytest.mark.parametrize(("hints", "amount"), [(0, 4), (1, 4), (2, 4), (3, 3), (4, 3)])
def test_hints_scale_only_their_question(hints: int, amount: int) -> None:
    # 4 x 1-min questions, hints all on the first: 3 + (1 - 0.25 n), floored at 0 for that question.
    calc = session_xp(KP, "passed", h("WWCC", [hints, 0, 0, 0]))
    assert calc.amount == amount
    assert calc.hints == hints
    assert calc.base_minutes == 4  # unscaled


def test_spec_example_two_hints_on_one_two_minute_question() -> None:
    # A 4-question KP pass (1, 2, 1, 1 min), 2 hints on the 2-min question: 1 + 2 x 0.5 + 1 + 1 = 4.
    positions = [*h("C", [0]), *h("C", [2], "2"), *h("WC", [0, 0])]
    calc = session_xp(KP, "passed", positions)
    assert (calc.amount, calc.grade, calc.hints, calc.base_minutes) == (
        4,
        XpGrade.passed,
        2,
        Decimal(5),
    )


def test_hints_on_every_question_match_the_old_rule() -> None:
    assert session_xp(KP, "passed", h("WWCC", [1, 1, 1, 1])).amount == 3  # 4 x 0.75


def test_positive_product_rounds_to_at_least_one() -> None:
    calc = session_xp(KP, "passed", h("CC", [2, 2], "0.5"))  # 1 x 0.5 x 1.2 = 0.6
    assert calc.amount == 1


def test_fully_hinted_pass_earns_zero() -> None:
    assert session_xp(KP, "passed", h("CC", [4, 4])).amount == 0


def test_hints_never_shrink_a_penalty() -> None:
    rushed = [PositionXp(Decimal(1), False, 1_000, hints=4) for _ in range(3)]
    assert session_xp(KP, "failed", rushed).amount == -1  # 0.25 x unscaled 3


def test_session_hint_total_can_be_given() -> None:
    # An unfinished multi-step item's hints count in the total but scale nothing.
    assert session_xp(KP, "passed", ps("CC"), hints=3).hints == 3


def test_is_rushed_floor_and_share() -> None:
    assert is_rushed(p(False, "0.5", 4_999))  # 15 % of 30 s = 4.5 s: the 5 s floor applies
    assert not is_rushed(p(False, "0.5", 5_000))
    assert is_rushed(p(False, "10", 89_999))  # 15 % of 10 min = 90 s
    assert not is_rushed(p(False, "10", 90_000))
    assert not is_rushed(p(True, "10", 1))


def test_multistep_time_is_the_sum_of_its_steps() -> None:
    # The service sums `time_taken_ms` over a position's step rows; 3 steps of 20 s = 60 s.
    assert not is_rushed(PositionXp(Decimal("6"), False, 20_000 * 3 * 10))
    assert is_rushed(PositionXp(Decimal("6"), False, 20_000))


def test_streak_from_days() -> None:
    today = date(2026, 11, 5)

    def d(n: int) -> date:
        return today - timedelta(days=n)

    assert streak_from_days({}, today) == (0, False)
    assert streak_from_days({d(1): True, d(2): True}, today) == (2, False)  # today unmet: kept
    assert streak_from_days({d(0): True, d(1): True}, today) == (2, True)
    assert streak_from_days({d(0): True, d(2): True}, today) == (1, True)  # a gap
    assert streak_from_days({d(1): False, d(2): True}, today) == (0, False)


def test_day_met() -> None:
    at = datetime(2026, 11, 5, tzinfo=UTC)
    assert not day_met([])
    assert not day_met([(None, None)])  # only a null-goal row (XP without a class)
    assert day_met([(15, at), (None, None)])
    assert not day_met([(15, at), (20, None)])
    # A met day whose XP later went negative stays met: `met_at` is never cleared.
    assert day_met([(15, at)])


def test_ist_week_start_boundary() -> None:
    # Sunday 23:59 IST = Sunday 18:29 UTC; Monday 00:00 IST = Sunday 18:30 UTC.
    sunday_late = datetime(2026, 11, 8, 18, 29, tzinfo=UTC)
    monday = datetime(2026, 11, 8, 18, 30, tzinfo=UTC)
    assert ist_week_start(sunday_late) == date(2026, 11, 2)
    assert ist_week_start(monday) == date(2026, 11, 9)


def test_competition_ranks() -> None:
    assert competition_ranks([9, 9, 4, 0, 0]) == [1, 1, 3, 4, 4]
    assert competition_ranks([]) == []


def test_implementation_tasks_earn_the_most() -> None:
    """A code item passed first try out-earns the best possible KP try of its course (Python).

    Across courses it doesn't hold: a maths KP of 5 long items (2+3+2+3+1 min) can earn 11.
    A KP try serves at most 5 distinct questions (repeats only after the pool is used up), so its
    best is a pass after misses over all of them (x1.0) or a 2/2 pass on the 2 longest (x1.2)."""
    bundle = load(DEFAULT_CONTENT_ROOT)
    best_kp = 0
    code = []
    python = next(c for c in bundle.courses if c.file.subject == "python")
    for concept in python.concepts:
        for kp in concept.file.kps:
            minutes = sorted((Decimal(str(i.expected_minutes)) for i in kp.items), reverse=True)
            five = minutes[:5]
            after_misses = [PositionXp(m, i >= len(five) - 2, SLOW) for i, m in enumerate(five)]
            two = [PositionXp(m, True, SLOW) for m in minutes[:2]]
            for positions in (after_misses, two):
                best_kp = max(best_kp, session_xp(KP, "passed", positions).amount)
        code += [
            Decimal(str(i.expected_minutes)) for i in concept.file.practice if i.type == "code"
        ]
    assert code, "the sample content has code practice items"
    least_code = min(
        session_xp(PRACTICE, "passed", [PositionXp(m, True, SLOW)]).amount for m in code
    )
    assert least_code > best_kp
