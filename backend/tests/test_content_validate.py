"""One minimal broken fixture per validator rule; each asserts the exact message line."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.content.loader import load
from app.content.validate import validate
from tests import content_fixtures as fx

CONCEPT = "content/maths/01-ch1/c1/concept.yaml"


def _issues(tmp_path: Path, t: dict[str, Any], level: str = "error") -> list[str]:
    bundle = load(fx.write(tmp_path, t))
    return [str(i) for i in validate(bundle) if i.level == level]


def _concept(t: dict[str, Any], course: str = "maths", index: int = 0) -> dict[str, Any]:
    concept: dict[str, Any] = t[course]["chapters"]["ch1"]["concepts"][index]
    return concept


def test_valid_fixture_has_no_issues(tmp_path: Path) -> None:
    assert validate(load(fx.write(tmp_path, fx.tree()))) == []


def test_cycle_within_a_course(tmp_path: Path) -> None:
    a = fx.concept("a", prereqs=[{"concept": "b", "weight": 0.5}])
    b = fx.concept("b", prereqs=[{"concept": "a", "weight": 0.5}])
    t = fx.tree(fx.course(concepts=[a, b]))
    assert _issues(tmp_path, t) == [
        "content/maths/01-ch1/a/concept.yaml: prereqs (a): "
        "prerequisite cycle: maths/a → maths/b → maths/a"
    ]


def test_cycle_across_courses(tmp_path: Path) -> None:
    m = fx.concept("algebra", prereqs=[{"concept": "physics/motion", "weight": 0.2}])
    p = fx.concept("motion", prereqs=[{"concept": "maths/algebra", "weight": 0.2}])
    t = fx.tree(fx.course(concepts=[m]), fx.course("physics", "physics", concepts=[p]))
    assert _issues(tmp_path, t) == [
        "content/maths/01-ch1/algebra/concept.yaml: prereqs (algebra): "
        "prerequisite cycle: maths/algebra → physics/motion → maths/algebra"
    ]


def test_missing_prereq_and_self_edge(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["prereqs"] = [
        {"concept": "physics/motion", "weight": 0.5},
        {"concept": "c1", "weight": 0.5},
        {"concept": "c1", "weight": 1.5},
    ]
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: prereqs[0] (c1): unknown concept 'physics/motion'",
        f"{CONCEPT}: prereqs[1] (c1): a concept can't be its own prerequisite",
        f"{CONCEPT}: prereqs[2] (c1): a concept can't be its own prerequisite",
        f"{CONCEPT}: prereqs[2] (c1): weight must be > 0 and <= 1, with at most 2 decimals",
    ]


def test_missing_misconception(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["misconception_check"]["answer"]["mcq"]["options"][1]["misconception"] = "nope"
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: misconception_check (check): option b: unknown misconception 'nope'"
    ]


def test_key_prereq_must_be_direct(tmp_path: Path) -> None:
    a = fx.concept("a")
    b = fx.concept("b")
    b["kps"][0]["key_prereqs"] = ["a"]
    t = fx.tree(fx.course(concepts=[a, b]))
    assert _issues(tmp_path, t) == [
        "content/maths/01-ch1/b/concept.yaml: kps[0] (kp1): "
        "key prereq 'a' is not one of this concept's direct prereqs"
    ]


def test_two_kps(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"].pop()
    assert _issues(tmp_path, t) == [f"{CONCEPT}: kps (c1): a concept needs 3-4 KPs (found 2)"]


def test_pool_weight_5(tmp_path: Path) -> None:
    t = fx.tree()
    items = _concept(t)["kps"][0]["items"]
    del items[1:3]  # 1 param (2) + fixed (1) + mcq (1) = 4 → add one fixed = 5
    items.append(fx.fixed_item("kp1-q6"))
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0] (kp1): question pool is too small: weight 5, needs >= 6 "
        "(fixed item = 1, param item = 2)"
    ]


def test_mcq_with_two_correct(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][4]["answer"]["mcq"]["options"][1] = {
        "id": "b",
        "text": "x = 2.0",
        "correct": True,
    }
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0].items[4] (kp1-q5): an MCQ needs exactly one correct option (found 2)",
        f"{CONCEPT}: kps[0].items[4] (kp1-q5): tag at least one distractor with a misconception",
    ]


def test_sigfig_without_sigfigs(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][1]["items"][2]["answer"] = {"numeric": {"value": "x", "mode": "sigfig"}}
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[1].items[2] (kp2-q3): sigfigs is required when mode is sigfig"
    ]


def test_unsatisfiable_constraints(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][0]["constraints"] = ["a > 100"]
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0].items[0] (kp1-q1): constraints are never satisfied"
    ]


def test_rarely_satisfiable_constraints(tmp_path: Path) -> None:
    t = fx.tree()
    item = _concept(t)["kps"][0]["items"][0]
    item["params"]["a"] = {"min": 1, "max": 1000, "step": 1}
    item["params"]["b"] = {"min": 1, "max": 1000, "step": 1}
    item["constraints"] = ["a == b"]
    [error] = _issues(tmp_path, t)
    assert error.startswith(f"{CONCEPT}: kps[0].items[0] (kp1-q1): constraints hold for only ")
    assert error.endswith(" of 50 seeds (need >= 48)")


def test_division_by_zero_for_some_seed(tmp_path: Path) -> None:
    t = fx.tree()
    item = _concept(t)["kps"][0]["items"][0]
    item["params"]["a"] = {"min": 0, "max": 9, "step": 1}
    [error] = _issues(tmp_path, t)
    assert error.startswith(f"{CONCEPT}: kps[0].items[0] (kp1-q1): seed ")
    assert error.endswith(": derived x is not a finite real number (division by zero?)")


def test_sigfig_value_zero_for_some_seed(tmp_path: Path) -> None:
    t = fx.tree()
    item = _concept(t)["kps"][0]["items"][0]
    item["params"]["b"] = {"min": 0, "max": 9, "step": 1}
    item["answer"] = {"numeric": {"value": "x", "mode": "sigfig", "sigfigs": 2}}
    [error] = _issues(tmp_path, t)
    assert error.endswith(": value is 0, which has no sig figs")


def test_exact_infinite_decimal(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][3]["answer"] = {"numeric": {"value": "1/3", "mode": "exact"}}
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0].items[3] (kp1-q4): seed 0: value 1/3 is not a finite decimal; "
        "use mode sigfig or tolerance"
    ]


def test_too_few_distinct_prompts(tmp_path: Path) -> None:
    t = fx.tree()
    item = _concept(t)["kps"][0]["items"][0]
    item["params"] = {"a": {"choices": [2, 4]}, "b": {"choices": [8]}}
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0].items[0] (kp1-q1): params give only 2 distinct prompts over 50 seeds "
        "(need >= 5)"
    ]


def test_unparsable_unit(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][3]["answer"]["numeric"]["unit"] = "mps"
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0].items[3] (kp1-q4): can't parse unit 'mps': unknown name 'mps'"
    ]


def test_unknown_placeholder(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][0]["prompt"] = "Solve {{a}}x = {{c}}."
    issues = _issues(tmp_path, t)
    assert issues == [f"{CONCEPT}: kps[0].items[0] (kp1-q1): unknown placeholder {{{{c}}}}"]


def test_bad_expression_answer(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][3] = fx.fixed_item(
        "kp1-q4",
        type="expression",
        answer={"expression": {"value": "2*x + y", "variables": ["x"], "sympy_mode": "equivalent"}},
    )
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: kps[0].items[3] (kp1-q4): expression: unknown name 'y'"
    ]


def test_duplicate_item_ids_across_kps(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][1]["items"][0]["id"] = "kp1-q1"
    issues = _issues(tmp_path, t)
    assert issues == [
        f"{CONCEPT}: kps[0].items[0] (kp1-q1): duplicate item id in this concept "
        "(item ids are per concept)",
        f"{CONCEPT}: kps[1].items[0] (kp1-q1): duplicate item id in this concept "
        "(item ids are per concept)",
    ]


def test_one_course_per_subject(tmp_path: Path) -> None:
    other = fx.course("maths-2", "maths", concepts=[fx.concept("c2")])
    t = fx.tree(fx.course(), other)
    assert _issues(tmp_path, t) == [
        "content/maths-2/course.yaml: subject (maths-2): subject maths is already used by "
        "course 'maths' (one course per subject)"
    ]


def test_practice_and_check_rules(tmp_path: Path) -> None:
    t = fx.tree()
    c = _concept(t)
    c["practice"] = [fx.fixed_item("practice-1")]
    c["misconception_check"]["bloom"] = "apply"
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: misconception_check (check): bloom must be remember or understand "
        "(Learn layer)",
        f"{CONCEPT}: practice[0] (practice-1): practice items must be multistep or code",
    ]


ImageSetup = Callable[[Path], str]


def _oversize(d: Path) -> str:
    (d / "img").mkdir()
    (d / "img" / "big.png").write_bytes(b"0" * (500 * 1024 + 1))
    return "img/big.png"


def _escaping(d: Path) -> str:
    return "../c2/img/x.svg"


def _absolute(d: Path) -> str:
    return "https://example.com/x.png"


def _scripted(d: Path) -> str:
    (d / "img").mkdir()
    (d / "img" / "x.svg").write_text('<svg onload="alert(1)"></svg>')
    return "img/x.svg"


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (_oversize, "image 'img/big.png' is larger than 500 KB"),
        (_escaping, "image '../c2/img/x.svg' must stay inside the concept folder"),
        (
            _absolute,
            "image 'https://example.com/x.png' must be a relative path inside the concept folder",
        ),
        (_scripted, "image 'img/x.svg' contains scripts or event handlers"),
    ],
)
def test_bad_images(tmp_path: Path, setup: ImageSetup, message: str) -> None:
    content = fx.write(tmp_path, fx.tree())
    d = fx.concept_dir(content)
    ref = setup(d)
    (d / "intro.md").write_text(f"# Intro\n\n![diagram]({ref})\n")
    errors = [str(i) for i in validate(load(content)) if i.level == "error"]
    assert errors == [f"content/maths/01-ch1/c1/intro.md: {message}"]


def test_external_links_must_be_youtube(tmp_path: Path) -> None:
    content = fx.write(tmp_path, fx.tree())
    d = fx.concept_dir(content)
    (d / "intro.md").write_text(
        "[ok](https://www.youtube.com/watch?v=abc) [bad](https://example.com) [rel](kp-1-worked.md)"
    )
    errors = [str(i) for i in validate(load(content))]
    assert errors == [
        "content/maths/01-ch1/c1/intro.md: link 'https://example.com': "
        "external links must be https YouTube links"
    ]


def test_code_items_run_the_reference_solution(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["practice"].append(
        {
            "id": "practice-2",
            "type": "code",
            "bloom": "create",
            "expected_minutes": 5,
            "prompt": "Write `double(n)`.",
            "answer": {
                "code": {
                    "entry": "double",
                    "starter": "def double(n):\n    pass\n",
                    "solution": "def double(n):\n    return n * 2\n",
                    "tests": [
                        {"args": [1], "expected": 2, "visible": True},
                        {"args": [3], "expected": 7},
                        {"args": [0], "expected": 0},
                    ],
                }
            },
        }
    )
    assert _issues(tmp_path, t) == [
        f"{CONCEPT}: practice[1] (practice-2): test 1: returned 6, expected 7"
    ]


# --- warnings -------------------------------------------------------------------------------------


def test_warning_unused_param(tmp_path: Path) -> None:
    t = fx.tree()
    _concept(t)["kps"][0]["items"][0]["params"]["unused"] = {"choices": [1, 2]}
    assert _issues(tmp_path, t, "warning") == [
        f"{CONCEPT}: kps[0].items[0] (kp1-q1): param 'unused' is never used"
    ]
    assert _issues(tmp_path / "x", t) == []


def test_warning_pool_below_8(tmp_path: Path) -> None:
    t = fx.tree()
    del _concept(t)["kps"][0]["items"][3]  # weight 7
    assert _issues(tmp_path, t, "warning") == [
        f"{CONCEPT}: kps[0] (kp1): question pool weight is 7; aim for >= 8"
    ]


def test_warning_unreferenced_markdown(tmp_path: Path) -> None:
    content = fx.write(tmp_path, fx.tree())
    (fx.concept_dir(content) / "draft.md").write_text("draft")
    assert [str(i) for i in validate(load(content))] == [
        "content/maths/01-ch1/c1/draft.md: Markdown file is not referenced from concept.yaml"
    ]


def test_warning_too_many_mcqs(tmp_path: Path) -> None:
    t = fx.tree()
    items = _concept(t)["kps"][0]["items"]
    items.append(fx.mcq_item("kp1-q6"))
    assert _issues(tmp_path, t, "warning") == [
        f"{CONCEPT}: kps[0] (kp1): 2 of 6 questions are MCQ; use MCQ sparingly (<= 30%)"
    ]
