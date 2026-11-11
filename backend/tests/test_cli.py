import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli
from app.cli import BAD_CODE, CliError, normalize_code
from app.services.erasure import DueResult
from tests import content_fixtures as fx

runner = CliRunner()


@pytest.mark.parametrize(
    ("raw", "code"), [("dps-rkp", "DPS-RKP"), (" tst ", "TST"), ("A1B2C3D4E5F6", "A1B2C3D4E5F6")]
)
def test_normalize_code(raw: str, code: str) -> None:
    assert normalize_code(raw) == code


@pytest.mark.parametrize("raw", ["AB", "ABCDEFGHIJKLM", "DPS RKP", "DPS_RKP", "स्कूल", ""])
def test_bad_codes_rejected(raw: str) -> None:
    with pytest.raises(CliError, match="School code must be"):
        normalize_code(raw)


def test_create_with_bad_code_exits_1_without_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("must not reach Supabase or the DB")

    monkeypatch.setattr(cli, "create_org", boom)
    result = runner.invoke(
        cli.app,
        [
            "org",
            "create",
            "--name",
            "X",
            "--code",
            "x!",
            "--admin-email",
            "a@x.in",
            "--admin-name",
            "A",
        ],
    )
    assert result.exit_code == 1
    assert BAD_CODE in result.output


def test_create_reports_errors_and_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    async def taken(*_a: object, **_k: object) -> None:
        raise CliError("School code DPS-RKP is already taken.")

    monkeypatch.setattr(cli, "create_org", taken)
    result = runner.invoke(
        cli.app,
        [
            "org",
            "create",
            "--name",
            "X",
            "--code",
            "DPS-RKP",
            "--admin-email",
            "a@x.in",
            "--admin-name",
            "A",
        ],
    )
    assert result.exit_code == 1
    assert "School code DPS-RKP is already taken." in result.output


def test_help_lists_org_commands() -> None:
    result = runner.invoke(cli.app, ["org", "--help"])
    assert result.exit_code == 0
    assert "create" in result.output and "list" in result.output


def test_content_check_ok_and_strict(tmp_path: Path) -> None:
    content = fx.write(tmp_path, fx.tree())
    result = runner.invoke(cli.app, ["content", "check", "--root", str(content)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "content OK: 1 courses, 1 concepts, 17 items"

    (fx.concept_dir(content) / "draft.md").write_text("draft")
    result = runner.invoke(cli.app, ["content", "check", "--root", str(content)])
    assert result.exit_code == 0
    assert "content OK: 1 courses, 1 concepts, 17 items (1 warnings)" in result.output
    result = runner.invoke(cli.app, ["content", "check", "--root", str(content), "--strict"])
    assert result.exit_code == 1
    assert "0 errors, 1 warnings" in result.output


def test_content_check_errors_exit_1(tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["kps"].pop()
    content = fx.write(tmp_path, t)
    result = runner.invoke(cli.app, ["content", "check", "--root", str(content)])
    assert result.exit_code == 1
    assert "content/maths/01-ch1/c1/concept.yaml: kps (c1): a concept needs 3-4 KPs (found 2)" in (
        result.output
    )
    assert "1 errors, 0 warnings" in result.output


# --- privacy (spec 014) ---------------------------------------------------------------------------


def test_run_due_prints_counts_and_exits_1_on_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = uuid.uuid4()

    async def ok() -> tuple[DueResult, int]:
        return DueResult(done=[uuid.uuid4(), uuid.uuid4()]), 7

    monkeypatch.setattr(cli, "_run_due", ok)
    result = runner.invoke(cli.app, ["privacy", "run-due"])
    assert result.exit_code == 0, result.output
    assert "Erasures completed: 2, failed: 0." in result.output
    assert "Purged the text of 7 tutor messages." in result.output

    async def bad() -> tuple[DueResult, int]:
        return DueResult(done=[], failed=[failed]), 0

    monkeypatch.setattr(cli, "_run_due", bad)
    result = runner.invoke(cli.app, ["privacy", "run-due"])
    assert result.exit_code == 1
    assert "failed: 1" in result.output and str(failed) in result.output


def test_export_passes_the_school_and_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[tuple[str, Path]] = []

    async def fake(code: str, out: Path) -> int:
        seen.append((code, out))
        return 3

    monkeypatch.setattr(cli, "_export", fake)
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path / "repo")  # tmp_path isn't in a checkout
    out = tmp_path / "export"
    result = runner.invoke(cli.app, ["privacy", "export", "--org", "abc", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert seen == [("ABC", out.resolve())]
    assert "Exported 3 students" in result.output


def test_export_refuses_paths_in_the_repo_or_not_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def boom(code: str, out: Path) -> int:
        raise AssertionError("must not touch the database")

    monkeypatch.setattr(cli, "_export", boom)
    inside = cli.REPO_ROOT / "exports"
    result = runner.invoke(cli.app, ["privacy", "export", "--org", "ABC", "--out", str(inside)])
    assert result.exit_code == 1 and cli.OUT_IN_REPO in result.output

    checkout = tmp_path / "other"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(CliError, match="inside a git repository"):
        cli.check_out_dir(checkout / "out")

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path / "repo")
    full = tmp_path / "full"
    full.mkdir()
    (full / "x.json").write_text("{}")
    result = runner.invoke(cli.app, ["privacy", "export", "--org", "ABC", "--out", str(full)])
    assert result.exit_code == 1 and cli.OUT_NOT_EMPTY in result.output
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.check_out_dir(empty) == empty.resolve()
