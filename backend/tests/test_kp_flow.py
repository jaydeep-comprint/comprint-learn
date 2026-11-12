"""KP flow rules (spec 005). Pure, no DB."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.services.kp_flow import (
    choose_next_item,
    is_open,
    kp_outcome,
    next_midnight_ist,
    review_outcome,
)


def seq(s: str) -> list[bool]:
    return [c == "C" for c in s]


@pytest.mark.parametrize(
    ("answers", "outcome"),
    [
        ("CC", "passed"),
        ("WCC", "passed"),
        ("CWCC", "passed"),
        ("WWCC", "passed"),
        ("WWW", "failed"),
        ("CWWW", "failed"),
        ("WCWCW", "failed"),
        ("CWCWC", "failed"),
        ("C", "active"),
        ("W", "active"),
        ("CW", "active"),
        ("WW", "active"),
        ("CWC", "active"),
    ],
)
def test_kp_outcome_examples(answers: str, outcome: str) -> None:
    assert kp_outcome(seq(answers)) == outcome


def _sessions(judge: object) -> list[list[bool]]:
    """Every answer sequence a session can produce (stopping at its first non-active outcome)."""
    out = []
    for n in range(1, 6):
        for combo in itertools.product([True, False], repeat=n):
            prefixes_active = all(judge(list(combo[:k])) == "active" for k in range(1, n))  # type: ignore[operator]
            if prefixes_active:
                out.append(list(combo))
    return out


def test_kp_outcome_exhaustive() -> None:
    for results in _sessions(kp_outcome):
        outcome = kp_outcome(results)
        if len(results) == 5:
            assert outcome != "active"
        if len(results) < 2:
            assert outcome == "active"
        if outcome == "passed":
            assert results[-2:] == [True, True]


@pytest.mark.parametrize(
    ("answers", "outcome"),
    [
        ("CCC", "passed"),
        ("CWC", "passed"),
        ("WCC", "passed"),
        ("CCWC", "passed"),
        ("WWW", "failed"),
        ("CCWWC", "failed"),
        ("CC", "active"),
        ("CCW", "active"),
        ("CCWW", "active"),
    ],
)
def test_review_outcome_examples(answers: str, outcome: str) -> None:
    assert review_outcome(seq(answers)) == outcome


def test_review_outcome_exhaustive() -> None:
    for results in _sessions(review_outcome):
        outcome = review_outcome(results)
        if len(results) == 5:
            assert outcome != "active"
        if len(results) < 3:
            assert outcome == "active"
        if outcome == "passed":
            assert results[-1] and sum(results[-3:]) >= 2


T0 = datetime(2026, 11, 1, tzinfo=UTC)


def test_choose_next_item_prefers_unseen_then_least_recent() -> None:
    pool = ["a", "b", "c", "d"]
    assert choose_next_item(pool, {}, set(), set()) == "a"
    history = {"a": T0, "b": T0 + timedelta(hours=1)}
    assert choose_next_item(pool, history, set(), set()) == "c"
    assert choose_next_item(pool, history, {"c"}, set()) == "d"
    assert choose_next_item(pool, history, {"c", "d"}, set()) == "a"  # least recently answered
    assert choose_next_item(pool, history, {"a", "c", "d"}, set()) == "b"


def test_choose_next_item_never_repeats_within_a_session() -> None:
    pool = ["a", "b", "c"]
    served: set[str] = set()
    for _ in range(3):
        nxt = choose_next_item(pool, {}, served, set())
        assert nxt is not None and nxt not in served
        served.add(nxt)
    # every item served: fixed items never repeat, param items may
    assert choose_next_item(pool, {}, served, set()) is None
    assert choose_next_item(pool, {"a": T0, "c": T0 - timedelta(1)}, served, {"a", "c"}) == "c"


def test_choose_next_item_is_deterministic() -> None:
    pool = ["x", "y", "z"]
    history = {"x": T0}
    assert len({choose_next_item(pool, history, set(), set()) for _ in range(10)}) == 1


def test_is_open() -> None:
    base = dict(
        failed=True,
        reopen_at=T0 + timedelta(hours=5),
        unresolved_remediations=0,
        passed_other_concept_since_fail=False,
        passed_review_since_fail=False,
    )
    assert is_open(**{**base, "failed": False}, now=T0)  # type: ignore[arg-type]
    assert not is_open(**base, now=T0)  # type: ignore[arg-type]
    assert is_open(**base, now=T0 + timedelta(hours=5))  # type: ignore[arg-type]
    assert is_open(**{**base, "passed_other_concept_since_fail": True}, now=T0)  # type: ignore[arg-type]
    assert is_open(**{**base, "passed_review_since_fail": True}, now=T0)  # type: ignore[arg-type]
    blocked = {**base, "unresolved_remediations": 1, "passed_other_concept_since_fail": True}
    assert not is_open(**blocked, now=T0 + timedelta(days=3))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # 23:59 IST on 1 Nov -> 00:00 IST 2 Nov (= 18:30 UTC 1 Nov), one minute later
        (datetime(2026, 11, 1, 18, 29, tzinfo=UTC), datetime(2026, 11, 1, 18, 30, tzinfo=UTC)),
        # exactly 00:00 IST -> the next midnight, a full day later
        (datetime(2026, 11, 1, 18, 30, tzinfo=UTC), datetime(2026, 11, 2, 18, 30, tzinfo=UTC)),
        (datetime(2026, 11, 1, 3, 0, tzinfo=UTC), datetime(2026, 11, 1, 18, 30, tzinfo=UTC)),
        # no DST in India: the same offset in summer
        (datetime(2026, 6, 15, 12, 0, tzinfo=UTC), datetime(2026, 6, 15, 18, 30, tzinfo=UTC)),
    ],
)
def test_next_midnight_ist(now: datetime, expected: datetime) -> None:
    assert next_midnight_ist(now) == expected


# --- spec 006: per-item results with multi-step positions -----------------------------------------


def test_position_results_counts_a_multistep_item_once_when_done() -> None:
    from types import SimpleNamespace

    from app.services.kp_flow import position_results

    ms, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def row(item: uuid.UUID, position: int, correct: bool, step: int = 0) -> Any:
        return SimpleNamespace(item_id=item, position=position, step=step, correct=correct)

    rows = [
        row(a, 1, True),
        row(ms, 2, True, 0),
        row(ms, 2, False, 1),
        row(ms, 2, True, 2),
        row(ms, 2, True, 3),  # 3 of 4 with the last: correct
        row(b, 3, False),
        row(ms, 4, True, 0),  # half-answered: not counted yet
    ]
    assert position_results(rows, {ms: 4}) == [True, True, False]
    assert position_results(rows[:4], {ms: 4}) == [True]
    assert position_results([row(ms, 1, True, 1), row(ms, 1, False, 0)], {ms: 2}) == [False]


def test_retry_prefers_new_numbers_over_a_fixed_item_whose_answer_was_shown() -> None:
    """Spec 015 review (area 4): after a failed session, an answered fixed item (its answer was
    shown) comes after answered param items, even when it was answered longer ago."""
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    pool = ["fixed1", "param1", "fixed2"]
    history = {"fixed1": t0, "param1": t0 + timedelta(hours=1), "fixed2": t0}
    assert choose_next_item(pool, history, set(), {"param1"}) == "param1"
    # Never-answered items still come first, fixed or not.
    assert choose_next_item([*pool, "fixed3"], history, set(), {"param1"}) == "fixed3"
    # With only answered fixed items left, the least recently answered one.
    assert choose_next_item(pool, history, {"param1"}, {"param1"}) == "fixed1"
