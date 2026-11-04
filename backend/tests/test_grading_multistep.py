"""Multi-step problems (spec 006): the 75% + last-step rule and per-step grading. Pure, no DB."""

import itertools
from typing import Any

import pytest

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.hashing import split_item
from app.content.loader import load
from app.content.params import sample
from app.grading import ShownOptions, grade
from app.grading.expression import answer_text
from app.grading.multistep import (
    multistep_outcome,
    needed,
    step_answer_doc,
    step_count,
    step_type,
)
from app.schemas.content import OptionPublic


@pytest.mark.parametrize("steps", [2, 3, 4, 5])
def test_outcome_every_pattern(steps: int) -> None:
    for pattern in itertools.product([True, False], repeat=steps):
        expected = sum(pattern) >= needed(steps) and pattern[-1]
        assert multistep_outcome(list(pattern), steps) == expected
    assert multistep_outcome([True], steps) is None


def test_outcome_examples() -> None:
    assert needed(2) == 2 and needed(3) == 3 and needed(4) == 3 and needed(5) == 4
    assert multistep_outcome([True, False, True, True], 4)
    assert not multistep_outcome([True, True, True, False], 4)
    assert not multistep_outcome([True, False], 2)


ANSWER: dict[str, Any] = {
    "spec": {
        "steps": [
            {
                "prompt": "time",
                "answer": {
                    "numeric": {"value": "2", "mode": "exact", "unit": "h"},
                    "expression": None,
                    "mcq": None,
                },
            },
            {
                "prompt": "expr",
                "answer": {
                    "numeric": None,
                    "expression": {"value": "2*x", "variables": ["x"], "sympy_mode": "equivalent"},
                    "mcq": None,
                },
            },
            {
                "prompt": "pick",
                "answer": {
                    "numeric": None,
                    "expression": None,
                    "mcq": {
                        "options": [
                            {"id": "a", "text": "A", "correct": False, "misconception": "m1"},
                            {"id": "b", "text": "B", "correct": True, "misconception": None},
                        ],
                        "shuffle": False,
                    },
                },
            },
        ]
    }
}


def test_step_grading_uses_the_usual_graders() -> None:
    assert step_count(ANSWER) == 3
    assert [step_type(ANSWER, i) for i in range(3)] == ["numeric", "expression", "mcq"]
    time = step_answer_doc(ANSWER, 0)
    assert grade("numeric", time, {}, "120", unit="min").correct
    assert grade("numeric", time, {}, "2", unit="km").note == "That unit doesn't measure time"
    assert grade("expression", step_answer_doc(ANSWER, 1), {}, "x+x").correct
    shown = ShownOptions([OptionPublic(id="a", text="A"), OptionPublic(id="b", text="B")])
    pick = step_answer_doc(ANSWER, 2)
    assert grade("mcq", pick, {}, "2", shown=shown).correct
    wrong = grade("mcq", pick, {}, "1", shown=shown)
    assert not wrong.correct and wrong.misconception == "m1"


def _multistep_items() -> list[Any]:
    bundle = load(DEFAULT_CONTENT_ROOT)
    return [
        pytest.param(item, id=f"{concept.qualified_id}/{item.id}")
        for concept in bundle.concepts
        for item in [*concept.file.practice, *(i for kp in concept.file.kps for i in kp.items)]
        if item.type.value == "multistep"
    ]


@pytest.mark.parametrize("item", _multistep_items())
def test_sample_multistep_items_accept_their_own_answers(item: Any) -> None:
    public, answer = split_item(item)
    for seed in range(20) if item.has_params else range(1):
        values = sample(item, seed)
        results = []
        for i in range(step_count(answer)):
            kind = step_type(answer, i)
            doc = step_answer_doc(answer, i)
            unit = doc["spec"].get("unit")
            shown = None
            if kind == "mcq":
                shown = ShownOptions([OptionPublic(**o) for o in public["steps"][i]["options"]])
            probe = grade(kind, doc, values, "1" if shown else "0", shown=shown, unit=unit)
            if kind == "numeric":
                response = probe.display_answer.removesuffix(f" {unit}")
            elif kind == "expression":
                response = answer_text(doc["spec"], values)
            else:
                response = probe.display_answer
            result = grade(kind, doc, values, response, shown=shown, unit=unit)
            assert result.correct, (seed, i, values, response, result)
            results.append(result.correct)
        assert multistep_outcome(results, step_count(answer))
