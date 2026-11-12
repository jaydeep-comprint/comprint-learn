"""Spec 015 §3: the load-test tools that don't need a database (tokens, pass criteria, seed
guards and ordering, answer helpers)."""

import uuid
from pathlib import Path

import pytest

from app.core.auth import TokenVerifier
from app.core.config import Settings
from app.loadtest_seed import SeedRefused, check_target, prereq_order
from loadtest import check
from loadtest.answers import option_id
from loadtest.tokens import mint

SUPABASE = "https://test-project.supabase.co"


async def _no_jwks() -> dict[str, object]:
    raise AssertionError("HS256 never fetches the JWKS")


async def test_minted_tokens_pass_the_real_hs256_verifier() -> None:
    verifier = TokenVerifier(
        fetch_jwks=_no_jwks,
        issuer=f"{SUPABASE}/auth/v1",
        hs256_secret="per-run-secret-0123456789abcdef",
    )
    user = uuid.uuid4()
    token = await verifier.verify(mint(user, "per-run-secret-0123456789abcdef", SUPABASE + "/"))
    assert token.user_id == user


async def test_a_token_with_another_secret_is_rejected() -> None:
    from app.core.auth import Unauthenticated

    verifier = TokenVerifier(
        fetch_jwks=_no_jwks, issuer=f"{SUPABASE}/auth/v1", hs256_secret="right"
    )
    with pytest.raises(Unauthenticated):
        await verifier.verify(mint(uuid.uuid4(), "wrong", SUPABASE))


# --- pass criteria ------------------------------------------------------------------------------

HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
    "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%\n"
)


def _csv(tmp_path: Path, rows: list[tuple[str, str, int, int, int, int, int]]) -> Path:
    lines = [HEADER]
    for method, name, n, fails, p50, p95, p99 in rows:
        lines.append(
            f"{method},{name},{n},{fails},{p50},{p50},1,{p99},100,1,0,"
            f"{p50},{p50},{p50},{p50},{p95},{p95},{p99},{p99},{p99},{p99},{p99}\n"
        )
    path = tmp_path / "run_stats.csv"
    path.write_text("".join(lines))
    return path


def test_check_passes_a_good_run(tmp_path: Path) -> None:
    path = _csv(
        tmp_path,
        [
            ("POST", "/learn/concepts/[c]/[k]/kps/[kp]/answer", 900, 2, 200, 700, 900),
            ("GET", "/me", 2000, 0, 50, 300, 500),
            ("", "Aggregated", 2900, 2, 80, 600, 1200),
        ],
    )
    rows, total = check.read_stats(path)
    assert (
        check.evaluate(
            rows, total, {"pool_errors": 0, "peak_db_connections": 8, "db_connection_limit": 10}
        )
        == []
    )


def test_check_reports_every_miss(tmp_path: Path) -> None:
    path = _csv(
        tmp_path,
        [
            ("POST", "/reviews/[c]/[k]/answer", 100, 0, 300, 800, 900),  # answer: 800 is a miss
            ("GET", "/classes/[id]/overview", 50, 0, 600, 1600, 2000),  # other: > 1500
            ("GET", "/me", 850, 12, 50, 100, 200),
            ("", "Aggregated", 1000, 12, 80, 900, 3100),  # 1.2% errors, p99 > 3 s
        ],
    )
    rows, total = check.read_stats(path)
    misses = check.evaluate(
        rows, total, {"pool_errors": 3, "peak_db_connections": 11, "db_connection_limit": 10}
    )
    assert len(misses) == 6
    assert any(m.startswith("error rate 1.20%") for m in misses)
    assert any("POST /reviews/[c]/[k]/answer" in m for m in misses)
    assert any("GET /classes/[id]/overview" in m for m in misses)
    assert any(m.startswith("overall p99") for m in misses)
    assert any("pool error" in m for m in misses)
    assert any(m.startswith("peak DB connections 11") for m in misses)


def test_check_exit_codes(tmp_path: Path) -> None:
    good = _csv(tmp_path, [("GET", "/me", 10, 0, 5, 10, 20), ("", "Aggregated", 10, 0, 5, 10, 20)])
    assert check.main(["check", str(good)]) == 0
    bad = _csv(tmp_path, [("GET", "/me", 10, 5, 5, 10, 20), ("", "Aggregated", 10, 5, 5, 10, 20)])
    assert check.main(["check", str(bad)]) == 1


# --- seed guards and ordering --------------------------------------------------------------------

TEST_URL = "postgresql://u:p@aws-0-x.pooler.supabase.com:5432/postgres"


def _settings(**kw: object) -> Settings:
    values: dict[str, object] = {
        "database_url": TEST_URL,
        "test_database_url": TEST_URL,
        "environment": "test",
    }
    values.update(kw)
    return Settings(**values)  # type: ignore[arg-type]


def test_seed_runs_only_on_the_test_database_in_test() -> None:
    assert check_target(_settings(), {}) == TEST_URL
    with pytest.raises(SeedRefused, match="ENVIRONMENT=test"):
        check_target(_settings(environment="development"), {})
    with pytest.raises(SeedRefused, match="ENVIRONMENT=test"):
        check_target(_settings(), {"ENVIRONMENT": "production"})
    with pytest.raises(SeedRefused, match="TEST_DATABASE_URL"):
        check_target(_settings(database_url="postgresql://u:p@dev-db:5432/postgres"), {})
    with pytest.raises(SeedRefused, match="TEST_DATABASE_URL"):
        check_target(_settings(test_database_url=None), {})


def test_prereq_order_puts_prerequisites_first() -> None:
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    concepts = [(c, 1, 1), (a, 1, 2), (b, 2, 1), (d, 1, 3)]  # (id, chapter pos, concept pos)
    edges = {(b, a), (c, b), (d, uuid.uuid4())}  # c needs b needs a; d's prereq is elsewhere
    order = prereq_order(concepts, edges)
    assert order.index(a) < order.index(b) < order.index(c)
    assert order[0] == a  # outline order among the ready ones: a (1,2) before d (1,3)
    assert set(order) == {a, b, c, d}


# --- answers -------------------------------------------------------------------------------------


def test_mcq_options_are_matched_by_text_not_position() -> None:
    authored = [{"id": "x", "text": "4 m"}, {"id": "y", "text": "8 m"}, {"id": "z", "text": "2 m"}]
    shown = [{"id": "1", "text": "2 m"}, {"id": "2", "text": "4 m"}, {"id": "3", "text": "8 m"}]
    assert option_id(shown, authored, "x", correct=True) == "2"
    assert option_id(shown, authored, "x", correct=False) in {"1", "3"}


def test_worked_out_answers_grade_as_intended_for_every_item() -> None:
    """The load test's "correct" answers really are correct (and its wrong ones wrong) for every
    KP and practice item in content/, through the server's own grader. Otherwise a run could
    pass while answering everything wrong."""
    from app.cli import DEFAULT_CONTENT_ROOT
    from app.content import hashing
    from app.content.loader import load
    from app.content.params import sample_answer
    from app.grading import grade, multistep
    from app.grading.mcq import ShownOptions
    from app.schemas.content import OptionPublic
    from loadtest.answers import quick

    def shown_for(options: list[dict[str, str]] | None) -> ShownOptions | None:
        if not options:
            return None
        # Any order the student might see: reversed, so ids never equal positions by luck.
        return ShownOptions([OptionPublic(id=o["id"], text=o["text"]) for o in reversed(options)])

    def check_part(
        kind: str,
        doc: dict[str, object],
        values: dict[str, object],
        authored: list[dict[str, str]] | None,
    ) -> None:
        shown = shown_for(authored)
        public = [o.model_dump() for o in shown.public()] if shown else None
        for correct in (True, False):
            fields = quick(kind, doc, values, public, authored, correct=correct)
            result = grade(
                kind, doc, values, fields["response"], shown=shown, unit=fields.get("unit")
            )
            assert result.correct is correct, (kind, doc, fields)

    bundle = load(DEFAULT_CONTENT_ROOT)
    checked = 0
    for course in bundle.courses:
        for chapter in course.chapters:
            for concept in chapter.concepts:
                items = [i for kp in concept.file.kps for i in kp.items] + concept.file.practice
                for item in items:
                    if item.type == "code":
                        continue
                    public, answer = hashing.split_item(item)
                    values = sample_answer(answer, 12345 if item.has_params else None)
                    if item.type == "multistep":
                        for step in range(len(public["steps"])):
                            check_part(
                                multistep.step_type(answer, step),
                                multistep.step_answer_doc(answer, step),
                                values,
                                public["steps"][step].get("options"),
                            )
                    else:
                        check_part(item.type, answer, values, public.get("options"))
                    checked += 1
    assert checked > 300
