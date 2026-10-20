"""A minimal valid content tree for validator/loader tests, written to a temp folder.

`tree()` returns plain dicts; tests mutate them to break exactly one rule, then `write(root, t)`.
"""

import copy
from pathlib import Path
from typing import Any

import yaml


def numeric_item(id_: str, **kw: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": id_,
        "type": "numeric",
        "bloom": "apply",
        "expected_minutes": 1,
        "prompt": "Solve {{a}}x = {{b}}.",
        "params": {"a": {"min": 2, "max": 9, "step": 1}, "b": {"min": 1, "max": 30, "step": 1}},
        "derived": {"x": "b / a"},
        "answer": {"numeric": {"value": "x", "mode": "tolerance", "rel_tol": 0.01}},
    }
    item.update(kw)
    return item


def fixed_item(id_: str, **kw: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": id_,
        "type": "numeric",
        "bloom": "apply",
        "expected_minutes": 1,
        "prompt": "What is 2 + 3?",
        "answer": {"numeric": {"value": 5, "mode": "exact"}},
    }
    item.update(kw)
    return item


def mcq_item(id_: str, **kw: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": id_,
        "type": "mcq",
        "bloom": "understand",
        "expected_minutes": 0.5,
        "prompt": "Which is a solution of x + 1 = 3?",
        "answer": {
            "mcq": {
                "options": [
                    {"id": "a", "text": "x = 2", "correct": True},
                    {"id": "b", "text": "x = 4", "misconception": "adds-instead"},
                ]
            }
        },
    }
    item.update(kw)
    return item


def multistep_item(id_: str) -> dict[str, Any]:
    return {
        "id": id_,
        "type": "multistep",
        "bloom": "analyze",
        "expected_minutes": 4,
        "prompt": "A rectangle has perimeter {{p}} cm and length {{l}} cm.",
        "params": {"p": {"choices": [20, 24, 28, 32, 36]}, "l": {"choices": [6, 7]}},
        "derived": {"w": "p / 2 - l"},
        "answer": {
            "multistep": {
                "steps": [
                    {
                        "prompt": "Write l + w.",
                        "answer": {"numeric": {"value": "p / 2", "mode": "exact"}},
                    },
                    {
                        "prompt": "Find w.",
                        "answer": {"numeric": {"value": "w", "unit": "cm", "mode": "exact"}},
                    },
                ]
            }
        },
    }


def kp(n: int, concept: str = "c1") -> dict[str, Any]:
    # Pool weight: 3 param items (2 each) + 2 fixed (1 each) = 8.
    return {
        "id": f"kp{n}",
        "title": f"Step {n}",
        "worked_example": f"kp-{n}-worked.md",
        "items": [
            numeric_item(f"kp{n}-q1"),
            numeric_item(f"kp{n}-q2"),
            numeric_item(f"kp{n}-q3"),
            fixed_item(f"kp{n}-q4"),
            mcq_item(f"kp{n}-q5"),
        ],
    }


def concept(id_: str = "c1", prereqs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": id_,
        "title": f"Concept {id_}",
        "summary": "A one-line summary.",
        "prereqs": prereqs or [],
        "intro": "intro.md",
        "misconception_check": mcq_item("check"),
        "kps": [kp(1), kp(2), kp(3)],
        "practice": [multistep_item("practice-1")],
    }


def course(id_: str = "maths", subject: str = "maths", concepts: list[Any] | None = None) -> Any:
    concepts = concepts if concepts is not None else [concept()]
    return {
        "course": {"id": id_, "title": id_.title(), "subject": subject, "chapters": ["ch1"]},
        "misconceptions": [
            {"id": "adds-instead", "title": "Adds instead", "description": "Adds both sides."},
        ],
        "chapters": {
            "ch1": {
                "chapter": {
                    "id": "ch1",
                    "title": "Chapter 1",
                    "grade": 9,
                    "concepts": [c["id"] for c in concepts],
                },
                "concepts": concepts,
            }
        },
    }


def tree(*courses: Any) -> dict[str, Any]:
    cs = courses or (course(),)
    return {c["course"]["id"]: copy.deepcopy(c) for c in cs}


def concept_dir(root: Path, course_id: str = "maths", concept_id: str = "c1") -> Path:
    return root / course_id / "01-ch1" / concept_id


def write(root: Path, t: dict[str, Any]) -> Path:
    """Writes the tree under `root/content` and returns that folder."""
    content = root / "content"
    for course_id, c in t.items():
        course_dir = content / course_id
        course_dir.mkdir(parents=True)
        _dump(course_dir / "course.yaml", c["course"])
        _dump(course_dir / "misconceptions.yaml", c["misconceptions"])
        for i, (chapter_id, ch) in enumerate(c["chapters"].items(), start=1):
            chapter_dir = course_dir / f"{i:02d}-{chapter_id}"
            chapter_dir.mkdir()
            _dump(chapter_dir / "chapter.yaml", ch["chapter"])
            for cpt in ch["concepts"]:
                d = chapter_dir / cpt["id"]
                d.mkdir()
                _dump(d / "concept.yaml", cpt)
                (d / "intro.md").write_text(f"# {cpt['title']}\n\nIntro.\n")
                for k in cpt.get("kps", []):
                    (d / k["worked_example"]).write_text("Worked example.\n")
    return content


def _dump(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
