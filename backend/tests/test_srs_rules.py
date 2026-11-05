"""Spaced repetition rules (spec 007), pure: ratings, the min-tomorrow rule, earliness, implicit
credit, struggling, queue order and the daily cap. No DB."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fsrs import Rating

from app.services import srs
from app.services.kp_flow import IST
from app.services.srs import QueueCard


def ist(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(UTC)


@pytest.mark.parametrize(
    ("passed", "all_correct", "rating"),
    [(True, True, Rating.Good), (True, False, Rating.Hard), (False, False, Rating.Again)],
)
def test_rating_for(passed: bool, all_correct: bool, rating: Rating) -> None:
    assert srs.rating_for(passed, all_correct) == rating


def test_rating_for_never_easy() -> None:
    assert all(srs.rating_for(p, c) != Rating.Easy for p in (True, False) for c in (True, False))


@pytest.mark.parametrize(("hh", "mm"), [(23, 59), (0, 1)])
def test_min_tomorrow_moves_today_to_next_ist_midnight(hh: int, mm: int) -> None:
    now = ist(2026, 11, 5, hh, mm)
    later_today = now + timedelta(seconds=30)
    assert srs.ist_day(later_today) == srs.ist_day(now)
    moved = srs.min_tomorrow(later_today, now)
    assert moved == srs.ist_midnight(srs.ist_day(now) + timedelta(days=1))
    assert srs.ist_day(moved) == srs.ist_day(now) + timedelta(days=1)


def test_min_tomorrow_keeps_later_days() -> None:
    now = ist(2026, 11, 5, 23, 59)
    due = ist(2026, 11, 8, 10, 0)
    assert srs.min_tomorrow(due, now) == due


def test_first_review_is_due_tomorrow_at_the_earliest() -> None:
    for hh, mm in ((0, 1), (12, 0), (23, 59)):
        at = ist(2026, 11, 5, hh, mm)
        first = srs.first_review(at)
        assert srs.ist_day(first.due) > srs.ist_day(at)
        assert first.stability > 0


def test_good_lengthens_and_again_shortens() -> None:
    at = ist(2026, 11, 1, 10, 0)
    first = srs.first_review(at)
    then = first.due
    good = srs.next_review(first.stability, first.difficulty, first.due, at, Rating.Good, then)
    again = srs.next_review(first.stability, first.difficulty, first.due, at, Rating.Again, then)
    assert good.stability > first.stability > again.stability
    assert good.due > again.due
    assert srs.ist_day(again.due) > srs.ist_day(then)  # min tomorrow


@pytest.mark.parametrize(
    ("elapsed_days", "expected"), [(0, 0.0), (2, 0.5), (4, 1.0), (10, 1.0), (-1, 0.0)]
)
def test_earliness(elapsed_days: int, expected: float) -> None:
    last = ist(2026, 11, 1, 10, 0)
    due = last + timedelta(days=4)
    assert srs.earliness(last, due, last + timedelta(days=elapsed_days)) == pytest.approx(expected)


def test_earliness_with_no_interval_is_full() -> None:
    at = ist(2026, 11, 1, 10, 0)
    assert srs.earliness(at, at, at) == 1.0


def test_implicit_share() -> None:
    assert srs.implicit_share(0.7, 3, "kp") == pytest.approx(0.7 / 3)
    assert srs.implicit_share(0.7, 0, "kp") == 0.0
    assert srs.implicit_share(0.7, 3, "review") == 0.7
    assert srs.implicit_share(0.7, 3, "brushup") == 0.7
    assert srs.implicit_share(0.7, 3, "practice") == 0.0


def test_learning_every_kp_of_a_concept_adds_up_to_the_weight() -> None:
    credit, fired = 0.0, False
    for _ in range(3):
        credit, fired = srs.credit_step(credit, srs.implicit_share(0.7, 3, "kp") * 1.0)
    assert not fired
    assert credit == pytest.approx(0.7)


def test_credit_reaching_one_fires_one_good_and_resets() -> None:
    credit, fired = srs.credit_step(0.0, 0.7)
    assert credit == pytest.approx(0.7) and fired is False
    credit, fired = srs.credit_step(credit, 0.7)  # 1.4: overflow dropped
    assert (credit, fired) == (0.0, True)
    assert srs.credit_step(0.0, 1 - 1e-7) == (0.0, True)  # float tolerance


def test_struggling() -> None:
    now = ist(2026, 11, 5, 10, 0)
    assert srs.struggling(1, None, now)
    assert srs.struggling(0, now - timedelta(days=29), now)
    assert not srs.struggling(0, now - timedelta(days=31), now)
    assert not srs.struggling(0, None, now)


def _card(n: int, subject: str, chapter: int, r: float) -> QueueCard:
    return QueueCard(uuid.UUID(int=n), subject, uuid.UUID(int=1000 + chapter), r)


def test_order_queue_lowest_retrievability_first_and_round_robin_by_subject() -> None:
    cards = [
        _card(1, "maths", 1, 0.9),
        _card(2, "maths", 2, 0.2),
        _card(3, "physics", 3, 0.5),
        _card(4, "maths", 1, 0.1),
        _card(5, "physics", 3, 0.6),
    ]
    out = [c.concept_id.int for c in srs.order_queue(cards)]
    # maths first (its lowest card, 4, is the lowest overall), alternating while both have cards
    assert out[0] == 4
    subjects = [next(c.subject for c in cards if c.concept_id.int == n) for n in out]
    assert subjects[:4] == ["maths", "physics", "maths", "physics"]
    assert sorted(out) == [1, 2, 3, 4, 5]


def test_order_queue_avoids_same_chapter_neighbours_when_it_can() -> None:
    cards = [
        _card(1, "maths", 1, 0.1),
        _card(2, "maths", 1, 0.2),
        _card(3, "maths", 2, 0.3),
        _card(4, "maths", 1, 0.4),
    ]
    out = srs.order_queue(cards)
    chapters = [c.chapter_id.int - 1000 for c in out]
    assert chapters == [1, 2, 1, 1]  # only one chapter-2 card: the last pair can't be split
    assert [c.concept_id.int for c in out][:2] == [1, 3]


def test_order_queue_is_stable() -> None:
    cards = [_card(n, ["maths", "physics", "python"][n % 3], n % 4, 0.5) for n in range(12)]
    first = srs.order_queue(cards)
    assert srs.order_queue(list(reversed(cards))) == first  # ties broken by concept id


def test_cap_left() -> None:
    assert srs.cap_left(0) == 5
    assert srs.cap_left(3) == 2
    assert srs.cap_left(7) == 0


def test_retrievability_falls_with_time() -> None:
    at = ist(2026, 11, 1, 10, 0)
    first = srs.first_review(at)
    r1 = srs.retrievability(first.stability, at, at + timedelta(days=1))
    r10 = srs.retrievability(first.stability, at, at + timedelta(days=10))
    assert 1 >= r1 > r10 > 0
