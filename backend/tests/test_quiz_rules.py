"""Quiz rules (spec 007), pure: item choice, XP per subject, the timer and the XP marks. No DB."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import XpGrade
from app.services import quiz
from app.services.quiz import Candidate, QuizConcept
from app.services.xp import QuizPos, quiz_xp

SUBJECTS = ["maths", "physics", "python"]


def _concepts(n: int, kps: int = 3, items: int = 5, params: bool = False) -> list[QuizConcept]:
    out = []
    for c in range(n):
        pools = [
            [Candidate(uuid.UUID(int=c * 1000 + k * 100 + i), params) for i in range(items)]
            for k in range(kps)
        ]
        out.append(
            QuizConcept(uuid.UUID(int=c + 1), SUBJECTS[c % 3], uuid.UUID(int=500 + c), pools)
        )
    return out


def _kp_of(item_id: uuid.UUID) -> int:
    return (item_id.int % 1000) // 100


@pytest.mark.parametrize("n", [3, 9, 15])
def test_choose_items_gives_ten_questions(n: int) -> None:
    picks = quiz.choose_items(_concepts(n))
    assert len(picks) == 10
    assert len({p.item_id for p in picks}) == 10  # fixed items never repeat


def test_choose_items_one_per_concept_first_lowest_retrievability() -> None:
    concepts = _concepts(15)
    picks = quiz.choose_items(concepts)
    assert {p.concept_id for p in picks} == {c.concept_id for c in concepts[:10]}


def test_choose_items_cycles_with_few_concepts_using_other_kps() -> None:
    picks = quiz.choose_items(_concepts(3))
    by_concept: dict[uuid.UUID, list[int]] = {}
    for p in picks:
        by_concept.setdefault(p.concept_id, []).append(_kp_of(p.item_id))
    assert sorted(len(v) for v in by_concept.values()) == [3, 3, 4]
    for kps in by_concept.values():
        assert len(set(kps[:3])) == 3  # a different KP each round where possible


def test_choose_items_interleaves_subjects() -> None:
    picks = quiz.choose_items(_concepts(9))
    subjects = [p.subject for p in picks]
    assert all(a != b for a, b in itertools.pairwise(subjects))


def test_choose_items_short_quiz_when_items_run_out() -> None:
    picks = quiz.choose_items(_concepts(3, kps=1, items=2))
    assert len(picks) == 6  # fixed items never repeat: 3 x 2


def test_choose_items_param_items_may_repeat() -> None:
    picks = quiz.choose_items(_concepts(1, kps=1, items=2, params=True))
    assert len(picks) == 10


def test_choose_items_nothing_learned() -> None:
    assert quiz.choose_items([]) == []
    assert quiz.choose_items(_concepts(2, kps=0)) == []


def q(correct: bool, answered: bool = True, minutes: str = "1", ms: int = 60_000) -> QuizPos:
    return QuizPos(Decimal(minutes), correct, answered, ms)


def test_quiz_xp_perfect() -> None:
    calc = quiz_xp([q(True), q(True), q(True)])
    assert (calc.amount, calc.grade) == (4, XpGrade.perfect)  # 3 x 1.2 = 3.6


def test_quiz_xp_passed_counts_only_correct_minutes() -> None:
    calc = quiz_xp([q(True, minutes="2"), q(False), q(True)])
    assert (calc.amount, calc.grade, calc.base_minutes) == (3, XpGrade.passed, Decimal(3))


def test_quiz_xp_poor() -> None:
    calc = quiz_xp([q(False), q(False, answered=False)])
    assert (calc.amount, calc.grade) == (0, XpGrade.poor)


def test_quiz_xp_rushed() -> None:
    calc = quiz_xp([q(False, ms=1000), q(False, ms=1000), q(True), q(False)])
    assert calc.grade == XpGrade.rushed
    assert calc.amount == -1  # 0.25 x 4 minutes = 1


def test_quiz_xp_unanswered_is_never_rushed() -> None:
    calc = quiz_xp([q(False, answered=False, ms=0), q(False, answered=False, ms=0), q(False)])
    assert calc.grade == XpGrade.poor


def test_quiz_xp_rushed_needs_fewer_than_half_correct() -> None:
    calc = quiz_xp([q(False, ms=1000), q(False, ms=1000), q(True), q(True)])
    assert calc.grade == XpGrade.passed


def test_deadline_and_grace() -> None:
    start = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    deadline = quiz.deadline_for(start, 10)
    assert deadline == start + timedelta(minutes=15)
    assert quiz.minutes_for(10) == 15
    assert not quiz.is_over(deadline - timedelta(seconds=1), deadline)
    assert quiz.is_over(deadline, deadline)
    assert not quiz.is_late(deadline + timedelta(seconds=30), deadline)
    assert quiz.is_late(deadline + timedelta(seconds=31), deadline)


def test_marks() -> None:
    assert quiz.should_create(150, 150, 3)
    assert not quiz.should_create(149, 150, 3)
    assert not quiz.should_create(500, 150, 2)  # fewer than 3 learned concepts
    # 150 -> 470 XP in one jump gives one quiz; the next mark counts from the end of the quiz
    assert quiz.next_mark(470 + 12) == 632
    assert quiz.next_mark(140) == 290  # cancel sets it the same way
