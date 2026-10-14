import pytest
from typer.testing import CliRunner

from app import cli
from app.cli import BAD_CODE, CliError, normalize_code

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
