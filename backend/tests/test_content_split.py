"""The never-to-client rule: `public` holds no answer key, and API item shapes come only from it."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.cli import DEFAULT_CONTENT_ROOT
from app.content.hashing import split_item
from app.content.loader import load
from app.content.schema import Item
from app.schemas.content import ItemPublic
from tests import content_fixtures as fx

FORBIDDEN = {"correct", "misconception", "solution", "derived", "constraints", "explanation"}

CODE_ITEM = {
    "id": "code-1",
    "type": "code",
    "bloom": "create",
    "expected_minutes": 5,
    "prompt": "Write `f(n)`.",
    "explanation": "Double it.",
    "answer": {
        "code": {
            "entry": "f",
            "starter": "def f(n):\n    pass\n",
            "solution": "def f(n):\n    return 2 * n  # SECRET-SOLUTION\n",
            "tests": [
                {"args": [1], "expected": 2, "visible": True},
                {"args": [77], "expected": 154},
                {"stdin": "hidden-stdin", "expected_stdout": "hidden-out"},
            ],
        }
    },
}


def _keys(data: Any) -> set[str]:
    if isinstance(data, dict):
        return set(data) | {k for v in data.values() for k in _keys(v)}
    if isinstance(data, list):
        return {k for v in data for k in _keys(v)}
    return set()


def _sample_items() -> list[Item]:
    bundle = load(DEFAULT_CONTENT_ROOT)
    items = []
    for c in bundle.concepts:
        items += [c.file.misconception_check, *c.file.practice]
        items += [i for kp in c.file.kps for i in kp.items]
    return items


def _fixture_items() -> list[Item]:
    c = fx.concept()
    raw = [c["misconception_check"], *c["practice"], *(i for kp in c["kps"] for i in kp["items"])]
    return [Item.model_validate(r) for r in [*raw, CODE_ITEM]]


@pytest.mark.parametrize("source", ["sample", "fixture"])
def test_public_never_contains_answer_keys(source: str) -> None:
    items = _sample_items() if source == "sample" else _fixture_items()
    if source == "sample" and not items:
        pytest.skip("no sample content yet")
    for item in items:
        public, answer = split_item(item)
        assert not (_keys(public) & FORBIDDEN), item.id
        assert "params" not in public and answer["params"] == {
            k: v.model_dump(mode="json", exclude_defaults=True) for k, v in item.params.items()
        }
        model = ItemPublic.from_row(SimpleNamespace(public=public))
        assert model.model_dump(mode="json", exclude_unset=True) == public


def test_hidden_tests_and_solution_stay_server_side() -> None:
    public, answer = split_item(Item.model_validate(CODE_ITEM))
    text = str(public)
    assert "SECRET-SOLUTION" not in text and "77" not in text and "hidden" not in text
    assert public["code"]["tests"] == [{"args": [1], "expected": 2}]
    assert "SECRET-SOLUTION" in answer["spec"]["solution"]
    assert answer["explanation"] == "Double it."


def test_mcq_answer_lives_in_answer() -> None:
    public, answer = split_item(Item.model_validate(fx.mcq_item("q")))
    assert public["options"] == [{"id": "a", "text": "x = 2"}, {"id": "b", "text": "x = 4"}]
    assert answer["correct"] == "a"
    assert answer["misconceptions"] == {"b": "adds-instead"}


def test_numeric_public_shows_the_unit_only() -> None:
    public, answer = split_item(Item.model_validate(fx.multistep_item("m")))
    assert public["steps"][1] == {"prompt": "Find w.", "type": "numeric", "unit": "cm"}
    assert answer["derived"] == {"w": "p / 2 - l"}


def test_from_row_rejects_leaked_keys() -> None:
    public, _ = split_item(Item.model_validate(fx.mcq_item("q")))
    public["options"][0]["correct"] = True
    with pytest.raises(ValueError, match="Extra inputs"):
        ItemPublic.from_row(SimpleNamespace(public=public))


def test_sample_root_exists() -> None:
    assert Path(DEFAULT_CONTENT_ROOT).name == "content"
