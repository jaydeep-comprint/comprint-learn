"""Pure Learn-layer helpers: outline borrowing/placement, lesson status, stable option shuffle."""

import uuid

from app.models import ConceptStatus
from app.services.frontier import concept_status
from app.services.learn import build_outline, lesson_steps, shuffled_order

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


def test_concept_status() -> None:
    a, b, c = (uuid.uuid4() for _ in range(3))
    prereqs = {b: [a], c: [b]}
    ip, learned = ConceptStatus.in_progress, ConceptStatus.learned
    assert concept_status(a, {}, prereqs) == "ready"
    assert concept_status(b, {}, prereqs) == "locked"
    assert concept_status(c, {}, prereqs) == "locked"
    assert concept_status(b, {a: ip}, prereqs) == "locked"  # a only in progress
    assert concept_status(b, {a: learned}, prereqs) == "ready"
    assert concept_status(a, {a: ip}, prereqs) == "in_progress"
    assert concept_status(a, {a: learned}, prereqs) == "learned"
    # In progress or learned never re-locks (e.g. a prereq being relearned).
    assert concept_status(c, {c: ip}, prereqs) == "in_progress"
    assert concept_status(c, {c: learned, b: ip}, prereqs) == "learned"


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
    assert lesson_steps(["kp1", "kp2"], has_check=True) == [
        "intro",
        "check",
        "kp:kp1",
        "kpq:kp1",
        "kp:kp2",
        "kpq:kp2",
    ]
    assert lesson_steps(["kp1"], has_check=False) == ["intro", "kp:kp1", "kpq:kp1"]


def test_shown_options_hide_authored_ids() -> None:
    from app.grading.mcq import ShownOptions as _ShownOptions
    from app.schemas.content import OptionPublic

    shown = _ShownOptions([OptionPublic(id="c", text="C"), OptionPublic(id="a", text="A")])
    assert [(o.id, o.text) for o in shown.public()] == [("1", "C"), ("2", "A")]
    assert shown.to_authored("2") == "a"
    assert shown.to_authored("1") == "c"
    for bad in ["0", "3", "a", "", "-1", "1.0", "²"]:
        assert shown.to_authored(bad) is None
    assert shown.to_client("a") == "2"
    assert shown.to_client("zzz") == ""


def test_attempt_upsert_predicate_is_a_literal() -> None:
    """A bound `context = $n` breaks ON CONFLICT inference under generic plans (asyncpg)."""
    import uuid as _uuid

    from sqlalchemy.dialects import postgresql

    from app.services.learn import learn_attempt_insert

    stmt = learn_attempt_insert(id=_uuid.uuid4(), context="learn")
    sql = str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert "ON CONFLICT (student_id, item_id) WHERE context = 'learn' DO NOTHING" in sql
