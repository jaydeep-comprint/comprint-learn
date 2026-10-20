from pathlib import Path

from app.content.loader import load
from tests import content_fixtures as fx


def _errors(tmp_path: Path, t: dict[str, object]) -> list[str]:
    bundle = load(fx.write(tmp_path, t))
    return [str(i) for i in bundle.issues if i.level == "error"]


def test_valid_fixture_parses(tmp_path: Path) -> None:
    bundle = load(fx.write(tmp_path, fx.tree()))
    assert bundle.issues == []
    [course] = bundle.courses
    [concept] = course.concepts
    assert concept.qualified_id == "maths/c1"
    assert concept.file.kps[0].items[0].has_params
    assert concept.markdown["intro.md"].startswith("# Concept c1")


def test_unknown_key_names_the_path(tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["kps"][1]["items"][2]["answer"]["numeric"][
        "unti"
    ] = "m"
    assert _errors(tmp_path, t) == [
        "content/maths/01-ch1/c1/concept.yaml: kps[1].items[2] (kp2-q3): "
        "answer.numeric.unti: unknown key (check the spelling)"
    ]


def test_bad_slug_names_the_path(tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["kps"][0]["items"][0]["id"] = "Q_1"
    [error] = _errors(tmp_path, t)
    assert error.startswith(
        "content/maths/01-ch1/c1/concept.yaml: kps[0].items[0] (Q_1): id: String should match"
    )


def test_wrong_enum_names_the_path(tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["practice"][0]["bloom"] = "apply-ish"
    [error] = _errors(tmp_path, t)
    assert error.startswith(
        "content/maths/01-ch1/c1/concept.yaml: practice[0] (practice-1): bloom: Input should be"
    )


def test_course_level_errors(tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["course"]["subject"] = "chemistry"
    [error] = _errors(tmp_path, t)
    assert error.startswith("content/maths/course.yaml: (maths): subject: Input should be")


def test_answer_key_must_match_type(tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["kps"][0]["items"][3]["type"] = "expression"
    assert _errors(tmp_path, t) == [
        "content/maths/01-ch1/c1/concept.yaml: kps[0].items[3] (kp1-q4): "
        "answer must have exactly one key, 'expression' (the item type)"
    ]


def test_duplicate_yaml_keys_are_errors(tmp_path: Path) -> None:
    content = fx.write(tmp_path, fx.tree())
    path = content / "maths" / "course.yaml"
    path.write_text(path.read_text() + "title: Again\n")
    [issue] = load(content).issues
    assert issue.path == "content/maths/course.yaml"
    assert "duplicate key 'title'" in issue.message


def test_missing_and_unreferenced_files(tmp_path: Path) -> None:
    content = fx.write(tmp_path, fx.tree())
    d = fx.concept_dir(content)
    (d / "kp-2-worked.md").unlink()
    (d / "notes.md").write_text("draft")
    (content / "maths" / "01-ch1" / "stray").mkdir()
    issues = [str(i) for i in load(content).issues]
    assert issues == [
        "content/maths/01-ch1/stray: folder is not a concept listed in chapter.yaml (ignored)",
        "content/maths/01-ch1/c1/concept.yaml: kps[1].worked_example (kp2): "
        "file 'kp-2-worked.md' not found",
        "content/maths/01-ch1/c1/notes.md: Markdown file is not referenced from concept.yaml",
    ]


def test_folder_names_must_match_ids(tmp_path: Path) -> None:
    content = fx.write(tmp_path, fx.tree())
    (content / "maths" / "01-ch1").rename(content / "maths" / "01-chapter-one")
    issues = [str(i) for i in load(content).issues]
    assert issues == [
        "content/maths/01-chapter-one: folder is not a chapter listed in course.yaml (ignored)",
        "content/maths/course.yaml: chapters: chapter 'ch1' has no folder "
        "(expected one named NN-ch1)",
    ]
