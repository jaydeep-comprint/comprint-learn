"""Pure Learn-layer helpers: outline borrowing/placement, lesson status, stable option shuffle."""

import uuid
from datetime import UTC, datetime

from app.services.learn import build_outline, lesson_status, lesson_steps, shuffled_order

# Concepts are "<course>/<slug>"; the tie-break key is (course, slug) here.
KEY = {"maths": 0, "physics": 1, "python": 2}


def _key(c: str) -> tuple[int, str]:
    course, slug = c.split("/")
    return KEY[course], slug


def _order(own: list[str], prereqs: dict[str, list[str]]) -> list[str]:
    return [c for c, _ in build_outline(own, prereqs, _key)]


def test_own_order_is_kept_even_when_authored_out_of_order() -> None:
    own = ["physics/b", "physics/a", "physics/c"]
    assert _order(own, {"physics/b": ["physics/a"]}) == own


def test_cross_course_ancestor_before_its_first_dependant() -> None:
    own = ["physics/dist", "physics/speed", "physics/acc"]
    prereqs = {
        "physics/speed": ["physics/dist", "maths/lin"],
        "physics/acc": ["physics/speed", "maths/lin"],
    }
    pairs = build_outline(own, prereqs, _key)
    assert pairs == [
        ("physics/dist", "physics/dist"),
        ("maths/lin", "physics/speed"),  # shown in the chapter of the concept it precedes
        ("physics/speed", "physics/speed"),
        ("physics/acc", "physics/acc"),  # shared ancestor placed once
    ]


def test_transitive_closure_in_topological_order() -> None:
    prereqs = {"physics/c": ["maths/b"], "maths/b": ["maths/a"]}
    assert _order(["physics/c"], prereqs) == ["maths/a", "maths/b", "physics/c"]


def test_borrowed_ancestors_any_course() -> None:
    prereqs = {"python/p": ["physics/x"], "physics/x": ["maths/m"]}
    assert _order(["python/p"], prereqs) == ["maths/m", "physics/x", "python/p"]


def test_ties_broken_by_key_deterministically() -> None:
    prereqs = {"physics/c": ["python/z", "maths/y", "maths/x"]}
    expected = ["maths/x", "maths/y", "python/z", "physics/c"]
    assert _order(["physics/c"], prereqs) == expected
    reordered = {"physics/c": ["maths/x", "python/z", "maths/y"]}
    assert _order(["physics/c"], reordered) == expected


def test_ancestor_order_beats_tie_break() -> None:
    # maths/a sorts first but needs python/z, so python/z goes first.
    prereqs = {"physics/c": ["maths/a"], "maths/a": ["python/z"]}
    assert _order(["physics/c"], prereqs) == ["python/z", "maths/a", "physics/c"]


def test_own_ancestor_of_borrowed_is_not_moved() -> None:
    # physics/late is own: it stays in authored order even though maths/m (placed earlier) needs it.
    prereqs = {"physics/first": ["maths/m"], "maths/m": ["physics/late"]}
    assert _order(["physics/first", "physics/late"], prereqs) == [
        "maths/m",
        "physics/first",
        "physics/late",
    ]


def test_no_prereqs() -> None:
    assert _order([], {}) == []
    assert _order(["maths/a"], {}) == ["maths/a"]


def test_lesson_status() -> None:
    done = datetime(2026, 11, 1, tzinfo=UTC)
    prereqs = {"b": ["a"], "c": ["b"]}
    assert lesson_status("a", {}, prereqs) == "ready"
    assert lesson_status("b", {}, prereqs) == "locked"
    assert lesson_status("c", {}, prereqs) == "locked"
    assert lesson_status("b", {"a": None}, prereqs) == "locked"  # a only in progress
    assert lesson_status("b", {"a": done}, prereqs) == "ready"
    assert lesson_status("a", {"a": None}, prereqs) == "in_progress"
    assert lesson_status("a", {"a": done}, prereqs) == "finished"
    # In progress or finished never re-locks (e.g. a prereq added after starting).
    assert lesson_status("c", {"c": None}, prereqs) == "in_progress"
    assert lesson_status("c", {"c": done}, prereqs) == "finished"


def test_shuffled_order_is_stable_per_student_and_item() -> None:
    ids = ["a", "b", "c", "d", "e"]
    s1, s2, item = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first = shuffled_order(ids, s1, item)
    assert sorted(first) == ids
    assert shuffled_order(ids, s1, item) == first
    orders = {tuple(shuffled_order(ids, uuid.uuid4(), item)) for _ in range(30)}
    assert len(orders) > 1  # different students see different orders
    assert shuffled_order(ids, s2, item) == shuffled_order(ids, s2, item)


def test_lesson_steps() -> None:
    assert lesson_steps(["kp1", "kp2"], has_check=True) == ["intro", "check", "kp:kp1", "kp:kp2"]
    assert lesson_steps(["kp1"], has_check=False) == ["intro", "kp:kp1"]
