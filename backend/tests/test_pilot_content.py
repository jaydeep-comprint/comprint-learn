"""Spec 013: the pilot quality bar, checked on the real content/ tree (offline).

The validator's own thresholds stay as they are; this bar is stricter and lives only here. Each
subject PR adds its course to `PILOT_COURSES`; existing (spec 003) concepts are told apart by
`LEGACY`.
"""

from functools import cache

import pytest

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.loader import ContentBundle, LoadedConcept, load
from app.content.schema import Item, ItemType, McqAnswer, MultistepAnswer

# Course id -> active concept count once its subject PR lands.
PILOT_COURSES = {"maths-9-10": 8, "physics-9-10": 8}

# The 9 spec-003 concepts, with their prerequisites then (never changed: a new prereq would change
# frontiers of students who started them) and their one practice item then.
LEGACY: dict[str, tuple[dict[str, float], str]] = {
    "maths-9-10/linear-equations-two-variables": ({}, "practice-taxi"),
    "maths-9-10/pair-of-linear-equations-graphical": (
        {"linear-equations-two-variables": 0.6},
        "practice-triangle",
    ),
    "maths-9-10/pair-of-linear-equations-algebraic": (
        {"pair-of-linear-equations-graphical": 0.4, "linear-equations-two-variables": 0.5},
        "practice-tickets",
    ),
    "physics-9-10/distance-and-displacement": ({}, "practice-1"),
    "physics-9-10/speed-and-velocity": (
        {"distance-and-displacement": 0.7, "maths-9-10/linear-equations-two-variables": 0.2},
        "practice-1",
    ),
    "physics-9-10/acceleration": ({"speed-and-velocity": 0.7}, "practice-1"),
    "python-basics/variables-and-types": ({}, "practice-1"),
    "python-basics/conditionals": ({"variables-and-types": 0.5}, "practice-1"),
    "python-basics/loops": ({"conditionals": 0.4, "variables-and-types": 0.3}, "practice-1"),
}
# Every legacy concept's items then: `check`, `kp1-q1` … `kp3-q5`, and its practice item.
LEGACY_KP_ITEMS = {f"kp{k}-q{q}" for k in (1, 2, 3) for q in range(1, 6)}

MIN_POOL_WEIGHT = 10
MIN_QUICK = 2
MAX_MCQ_SHARE = 0.3
QUICK = (ItemType.numeric, ItemType.expression, ItemType.mcq)
# Spec 013 decision 3: new items only (existing ones aren't re-timed).
MINUTES = {
    "quick": (0.5, 2),
    "multistep": (4, 10),
    "kp_code": (2, 5),
    "practice_code": (5, 15),
}


@cache
def _bundle() -> ContentBundle:
    return load(DEFAULT_CONTENT_ROOT)


def _concepts() -> list[LoadedConcept]:
    return [c for c in _bundle().concepts if c.course in PILOT_COURSES]


def _ids(concepts: list[LoadedConcept]) -> list[str]:
    return [c.qualified_id for c in concepts]


CONCEPTS = _concepts()
PARAMS = pytest.mark.parametrize("concept", CONCEPTS, ids=_ids(CONCEPTS))


def _is_legacy(c: LoadedConcept) -> bool:
    return c.qualified_id in LEGACY


def _is_new_item(c: LoadedConcept, item: Item) -> bool:
    if not _is_legacy(c):
        return True
    return item.id not in LEGACY_KP_ITEMS | {"check", LEGACY[c.qualified_id][1]}


def _all_items(c: LoadedConcept) -> list[tuple[str, Item]]:
    f = c.file
    out = [("check", f.misconception_check)]
    out += [("kp", i) for kp in f.kps for i in kp.items]
    out += [("practice", i) for i in f.practice]
    return out


def test_pilot_courses_have_their_concepts() -> None:
    assert not [i for i in _bundle().issues if i.level == "error"]
    for course_id, count in PILOT_COURSES.items():
        course = next(c for c in _bundle().courses if c.file.id == course_id)
        assert len(course.concepts) == count, course_id


def test_legacy_concepts_still_exist() -> None:
    present = {c.qualified_id for c in _bundle().concepts}
    assert set(LEGACY) <= present


@PARAMS
def test_kp_count(concept: LoadedConcept) -> None:
    assert len(concept.file.kps) == (3 if _is_legacy(concept) else 4)


@PARAMS
def test_kp_pools(concept: LoadedConcept) -> None:
    for kp in concept.file.kps:
        weight = sum(2 if i.has_params else 1 for i in kp.items)
        assert weight >= MIN_POOL_WEIGHT, f"{kp.id}: pool weight {weight}"
        quick = sum(i.type in QUICK for i in kp.items)
        assert quick >= MIN_QUICK, f"{kp.id}: {quick} quick checks"
        mcqs = sum(i.type == ItemType.mcq for i in kp.items)
        assert mcqs / len(kp.items) <= MAX_MCQ_SHARE, f"{kp.id}: {mcqs}/{len(kp.items)} MCQ"


@PARAMS
def test_practice(concept: LoadedConcept) -> None:
    practice = concept.file.practice
    if _is_legacy(concept):
        assert len(practice) == 2
    else:
        assert 2 <= len(practice) <= 3
    for item in practice:
        if concept.course == "python-basics":
            assert item.type == ItemType.code, item.id
        else:
            assert item.type == ItemType.multistep and item.has_params, item.id


@PARAMS
def test_new_items_expected_minutes(concept: LoadedConcept) -> None:
    for where, item in _all_items(concept):
        if not _is_new_item(concept, item):
            continue
        if item.type in QUICK:
            band = "quick"
        elif item.type == ItemType.multistep:
            band = "multistep"
        else:
            band = "practice_code" if where == "practice" else "kp_code"
        lo, hi = MINUTES[band]
        assert lo <= item.expected_minutes <= hi, f"{item.id}: {item.expected_minutes} ({band})"


@PARAMS
def test_every_mcq_has_a_tagged_distractor(concept: LoadedConcept) -> None:
    for _, item in _all_items(concept):
        spec = item.spec
        mcqs = [spec] if isinstance(spec, McqAnswer) else []
        if isinstance(spec, MultistepAnswer):
            mcqs = [s.answer.mcq for s in spec.steps if s.answer.mcq is not None]
        for mcq in mcqs:
            assert any(o.misconception for o in mcq.options if not o.correct), item.id


@PARAMS
def test_prereqs_and_key_prereqs(concept: LoadedConcept) -> None:
    f = concept.file
    prereqs = {p.concept: p.weight for p in f.prereqs}
    if _is_legacy(concept):
        assert prereqs == LEGACY[concept.qualified_id][0]
        return
    if prereqs:
        assert any(kp.key_prereqs for kp in f.kps), "no KP has key_prereqs"


@PARAMS
def test_markdown_present(concept: LoadedConcept) -> None:
    f = concept.file
    assert concept.markdown.get(f.intro, "").strip()
    for kp in f.kps:
        assert concept.markdown.get(kp.worked_example, "").strip(), kp.id


def test_cross_course_edges_stay_light() -> None:
    """Physics may lean on Class 9 linear equations only, lightly (spec 013)."""
    for c in _concepts():
        for p in c.file.prereqs:
            if "/" in p.concept:
                assert p.concept == "maths-9-10/linear-equations-two-variables", c.qualified_id
                assert p.weight <= 0.3, c.qualified_id
