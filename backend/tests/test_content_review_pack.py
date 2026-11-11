"""Spec 013: `app content review-pack` renders a course, answers included, to one HTML file."""

import json
import re
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from app import cli
from app.content.loader import load
from app.content.review_pack import build_review_pack, pack_data
from tests import content_fixtures as fx

runner = CliRunner()

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
DATA_BLOCK = re.compile(r'<script type="application/json" id="pack">(.*?)</script>', re.DOTALL)


def _tree() -> dict[str, Any]:
    t = fx.tree()
    c = t["maths"]["chapters"]["ch1"]["concepts"][0]
    c["practice"].append(fx.code_item("practice-2"))
    return t


def _content(tmp_path: Path, t: dict[str, Any] | None = None) -> Path:
    content = fx.write(tmp_path, t or _tree())
    d = fx.concept_dir(content)
    (d / "img").mkdir()
    (d / "img" / "dot.svg").write_text(SVG)
    (d / "intro.md").write_text("# Intro\n\n![a dot](img/dot.svg)\n\nWith $x^2$.\n")
    return content


def _data(html: str) -> Any:
    m = DATA_BLOCK.search(html)
    assert m is not None
    return json.loads(m.group(1))


def _items(data: Any) -> dict[str, Any]:
    concept = data["chapters"][0]["concepts"][0]
    out = {"check": concept["check"]}
    for kp in concept["kps"]:
        out.update({i["id"]: i for i in kp["items"]})
    out.update({i["id"]: i for i in concept["practice"]})
    return out


def test_param_item_rendered_per_seed_fixed_item_once(tmp_path: Path) -> None:
    bundle = load(_content(tmp_path))
    data = pack_data(bundle, "maths", seeds=3)
    items = _items(data)
    param = items["kp1-q1"]
    assert param["pool_weight"] == 2 and param["params"]["a"] == {"min": 2, "max": 9, "step": 1}
    assert param["derived"] == {"x": "b / a"}
    assert [s["seed"] for s in param["samples"]] == [1, 2, 3]
    for s in param["samples"]:
        assert "{{" not in s["prompt"]
        a, b = (int(n) for n in re.findall(r"\d+", s["prompt"]))
        assert abs(float(s["answer"]) - b / a) <= 0.01 * b / a
    fixed = items["kp1-q4"]
    assert fixed["pool_weight"] == 1
    assert [s["seed"] for s in fixed["samples"]] == [None]
    assert fixed["samples"][0]["answer"] == "5"
    assert fixed["answer_spec"]["mode"] == "exact"


def test_mcq_marks_correct_and_names_misconceptions(tmp_path: Path) -> None:
    data = pack_data(load(_content(tmp_path)), "maths", seeds=3)
    options = _items(data)["kp1-q5"]["options"]
    assert options == [
        {"id": "a", "text": "x = 2", "correct": True, "misconception": None},
        {
            "id": "b",
            "text": "x = 4",
            "correct": False,
            "misconception": {"id": "adds-instead", "title": "Adds instead"},
        },
    ]
    assert data["misconceptions"][0]["description"] == "Adds both sides."


def test_multistep_steps_and_code_hidden_tests(tmp_path: Path) -> None:
    data = pack_data(load(_content(tmp_path)), "maths", seeds=2)
    items = _items(data)
    steps = items["practice-1"]["samples"][0]["steps"]
    assert len(steps) == 2 and steps[1]["answer"].endswith(" cm")
    code = items["practice-2"]["code"]
    assert code["solution"].startswith("def double")
    assert [t["visible"] for t in code["tests"]] == [True, False, False]
    assert code["tests"][2] == {"args": [0], "expected": 0, "visible": False}
    assert code["time_limit_ms"] == 2000
    assert items["practice-2"]["samples"] == []  # no params, nothing to sample


def test_html_has_answers_images_and_content_only_in_json(tmp_path: Path) -> None:
    t = _tree()
    c = t["maths"]["chapters"]["ch1"]["concepts"][0]
    c["kps"][0]["items"][3]["prompt"] = "Evil </script><script>alert(1)</script> & <b>x</b>"
    html = build_review_pack(load(_content(tmp_path, t)), "maths", seeds=3)
    assert html.count("<script") == 4  # katex, marked, the JSON block, the renderer
    assert "alert(1)" not in DATA_BLOCK.sub("", html)
    assert "</script><script>alert" not in html
    data = _data(html)
    assert _items(data)["kp1-q4"]["prompt"].startswith("Evil </script>")
    images = data["chapters"][0]["concepts"][0]["images"]
    assert images["img/dot.svg"].startswith("data:image/svg+xml;base64,")
    # Answers and hidden tests are in the file.
    assert '"solution"' in html and '"expected": 6' in html.replace('\\"', '"')


def test_deterministic(tmp_path: Path) -> None:
    bundle = load(_content(tmp_path))
    a = build_review_pack(bundle, "maths", seeds=3, generated="2026-11-11", sha="abc")
    b = build_review_pack(bundle, "maths", seeds=3, generated="2026-11-12", sha=None)
    da, db = _data(a), _data(b)
    da.pop("meta"), db.pop("meta")
    assert da == db
    assert a == build_review_pack(bundle, "maths", seeds=3, generated="2026-11-11", sha="abc")


def test_cli_writes_one_file_per_course(tmp_path: Path) -> None:
    content = _content(tmp_path)
    out = tmp_path / "packs"
    result = runner.invoke(
        cli.app, ["content", "review-pack", "--root", str(content), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == ["maths.html"]
    assert "maths.html" in result.output


def test_cli_unknown_course(tmp_path: Path) -> None:
    content = _content(tmp_path)
    result = runner.invoke(
        cli.app,
        ["content", "review-pack", "--root", str(content), "--out", str(tmp_path / "o")],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result = runner.invoke(
        cli.app,
        ["content", "review-pack", "--root", str(content), "--course", "nope"],
    )
    assert result.exit_code == 1 and "nope" in result.output


def test_cli_refuses_a_broken_tree(tmp_path: Path) -> None:
    t = _tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["kps"].pop()
    content = _content(tmp_path, t)
    out = tmp_path / "packs"
    result = runner.invoke(
        cli.app, ["content", "review-pack", "--root", str(content), "--out", str(out)]
    )
    assert result.exit_code == 1
    assert "a concept needs 3-4 KPs" in result.output
    assert not out.exists()
