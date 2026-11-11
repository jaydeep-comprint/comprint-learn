"""Operator CLI: `uv run app org create|list`, `uv run app content check|import|review-pack` and
`uv run app tutor eval|purge|flagged`."""

import asyncio
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import case, func, select

from app.api.deps import OrgScope
from app.content.importer import ImportReport, import_tree
from app.content.loader import ContentBundle, Issue, load
from app.content.review_pack import build_review_pack
from app.content.validate import has_errors, validate
from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.db.session import dispose_engine, get_sessionmaker
from app.models import AppUser, Organization, Role
from app.models.tenancy import SCHOOL_CODE_PATTERN
from app.services import tenancy, tutor
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

app = typer.Typer(no_args_is_help=True, add_completion=False)
org_app = typer.Typer(no_args_is_help=True, help="Schools (organizations).")
app.add_typer(org_app, name="org")
content_app = typer.Typer(
    no_args_is_help=True, help="Courses in content/ (validate, import, review pack)."
)
app.add_typer(content_app, name="content")
tutor_app = typer.Typer(
    no_args_is_help=True, help="AI tutor (eval, retention purge, safety flags)."
)
app.add_typer(tutor_app, name="tutor")
teacher_ai_app = typer.Typer(
    help="Teacher AI summaries (spec 011): the offline eval.", no_args_is_help=True
)
app.add_typer(teacher_ai_app, name="teacher-ai")

DEFAULT_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content"
RootOpt = Annotated[Path, typer.Option("--root", help="The content/ folder")]
# Spec 013: gitignored; the packs contain every answer.
DEFAULT_REVIEW_PACKS = DEFAULT_CONTENT_ROOT.parent / "review-packs"

BAD_CODE = "School code must be 3-12 characters: A-Z, 0-9 or '-'."
EMPTY_NAME = "School name and admin name can't be empty."


class CliError(Exception):
    pass


def normalize_code(code: str) -> str:
    code = code.strip().upper()
    if not re.fullmatch(SCHOOL_CODE_PATTERN, code):
        raise CliError(BAD_CODE)
    return code


async def create_org(
    admin: SupabaseAdmin, *, name: str, code: str, admin_email: str, admin_name: str
) -> Organization:
    """Creates the school and invites its first admin; nothing is left behind on failure."""
    code = normalize_code(code)
    name, admin_name, admin_email = name.strip(), admin_name.strip(), admin_email.strip()
    if not name or not admin_name:
        raise CliError(EMPTY_NAME)
    try:
        async with get_sessionmaker()() as session:
            taken = await session.scalar(select(Organization.id).where(Organization.code == code))
            if taken is not None:
                raise CliError(f"School code {code} is already taken.")
            org = Organization(name=name, code=code)
            session.add(org)
            await session.flush()
            # Invites first, then commits the org and the admin row together (see invite_teacher).
            await tenancy.invite_teacher(
                OrgScope.system(session, org.id), admin, admin_email, admin_name, is_admin=True
            )
            return org
    except ApiProblem as exc:
        raise CliError(exc.message or exc.code) from exc
    finally:
        await dispose_engine()


async def list_orgs() -> list[tuple[str, str, int, int]]:
    try:
        async with get_sessionmaker()() as session:
            stmt = (
                select(
                    Organization.code,
                    Organization.name,
                    func.count(case((AppUser.role == Role.teacher, 1))),
                    func.count(case((AppUser.role == Role.student, 1))),
                )
                .outerjoin(AppUser, AppUser.org_id == Organization.id)
                .group_by(Organization.id)
                .order_by(Organization.code)
            )
            return [(c, n, t, st) for c, n, t, st in (await session.execute(stmt)).all()]
    finally:
        await dispose_engine()


@org_app.command("create")
def org_create(
    name: Annotated[str, typer.Option(help="School name")],
    code: Annotated[str, typer.Option(help="3-12 chars, A-Z 0-9 -; students type it")],
    admin_email: Annotated[str, typer.Option(help="First admin's email (gets an invite)")],
    admin_name: Annotated[str, typer.Option(help="First admin's display name")],
) -> None:
    """Create a school and invite its first admin."""
    try:
        normalize_code(code)  # fail fast, before touching the database or Supabase
        org = asyncio.run(
            create_org(
                get_supabase_admin(),
                name=name,
                code=code,
                admin_email=admin_email,
                admin_name=admin_name,
            )
        )
    except CliError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Created {org.code} and sent the admin invite.")


@org_app.command("list")
def org_list() -> None:
    """Print each school's code, name and user counts."""
    rows = asyncio.run(list_orgs())
    if not rows:
        typer.echo("No schools yet.")
        return
    for code, name, teachers, students in rows:
        typer.echo(f"{code:<12}  {name}  ({teachers} teachers, {students} students)")


def print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        typer.echo(str(issue), err=issue.level == "error")


def summary(bundle: ContentBundle) -> str:
    items = sum(
        1 + sum(len(kp.items) for kp in c.file.kps) + len(c.file.practice) for c in bundle.concepts
    )
    return f"{len(bundle.courses)} courses, {len(bundle.concepts)} concepts, {items} items"


def check_content(root: Path, *, strict: bool) -> tuple[ContentBundle, list[Issue], bool]:
    """(bundle, issues, ok). Warnings fail only with `strict`."""
    bundle = load(root)
    issues = validate(bundle)
    return bundle, issues, not has_errors(issues, strict=strict)


@content_app.command("check")
def content_check(
    root: RootOpt = DEFAULT_CONTENT_ROOT,
    strict: Annotated[bool, typer.Option(help="Treat warnings as errors")] = False,
) -> None:
    """Validate every course in content/ (schema, references, graph, answers, code)."""
    bundle, issues, ok = check_content(root, strict=strict)
    print_issues(issues)
    if not ok:
        errors = sum(i.level == "error" for i in issues)
        typer.echo(f"{errors} errors, {len(issues) - errors} warnings", err=True)
        raise typer.Exit(1)
    warnings = f" ({len(issues)} warnings)" if issues else ""
    typer.echo(f"content OK: {summary(bundle)}{warnings}")


def _git_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


@content_app.command("review-pack")
def content_review_pack(
    root: RootOpt = DEFAULT_CONTENT_ROOT,
    course: Annotated[
        list[str] | None, typer.Option("--course", help="Course id (repeatable; default all)")
    ] = None,
    out: Annotated[Path, typer.Option("--out", help="Output folder")] = DEFAULT_REVIEW_PACKS,
    seeds: Annotated[int, typer.Option(min=1, max=20, help="Sample seeds per param item")] = 3,
) -> None:
    """Write one self-contained HTML file per course, with every answer, for reviewers."""
    bundle, issues, ok = check_content(root, strict=False)
    print_issues(issues)
    if not ok:
        errors = sum(i.level == "error" for i in issues)
        typer.echo(f"{errors} errors; no review pack written.", err=True)
        raise typer.Exit(1)
    known = [c.file.id for c in bundle.courses]
    wanted = course or known
    unknown = [c for c in wanted if c not in known]
    if unknown:
        typer.echo(f"unknown course: {', '.join(unknown)} (have: {', '.join(known)})", err=True)
        raise typer.Exit(1)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    sha = _git_sha(root)
    out.mkdir(parents=True, exist_ok=True)
    for course_id in wanted:
        html = build_review_pack(bundle, course_id, seeds=seeds, generated=generated, sha=sha)
        path = out / f"{course_id}.html"
        path.write_text(html, encoding="utf-8")
        typer.echo(f"wrote {path}")


async def import_content(root: Path, *, dry_run: bool) -> tuple[list[Issue], ImportReport | None]:
    try:
        return await import_tree(root, get_sessionmaker(), dry_run=dry_run)
    finally:
        await dispose_engine()


@content_app.command("import")
def content_import(
    root: RootOpt = DEFAULT_CONTENT_ROOT,
    dry_run: Annotated[bool, typer.Option(help="Show what would change; write nothing")] = False,
) -> None:
    """Validate, then import content/ into DATABASE_URL in one transaction (idempotent)."""
    issues, report = asyncio.run(import_content(root, dry_run=dry_run))
    print_issues(issues)
    if report is None:
        errors = sum(i.level == "error" for i in issues)
        typer.echo(f"{errors} errors, {len(issues) - errors} warnings; nothing imported.", err=True)
        raise typer.Exit(1)
    for line in report.lines():
        typer.echo(line)
    typer.echo("Dry run, nothing written." if dry_run else "Imported.")


async def _purge() -> int:
    try:
        async with get_sessionmaker()() as session:
            return await tutor.purge_text(session, datetime.now(UTC))
    finally:
        await dispose_engine()


@tutor_app.command("purge")
def tutor_purge() -> None:
    """Delete the text of tutor messages older than 180 days (counts and flags stay)."""
    n = asyncio.run(_purge())
    typer.echo(f"Purged the text of {n} tutor messages.")


async def _flagged(org: str | None) -> list[tutor.FlaggedRow]:
    try:
        async with get_sessionmaker()() as session:
            return await tutor.flagged(session, org)
    finally:
        await dispose_engine()


@tutor_app.command("flagged")
def tutor_flagged(
    org: Annotated[str | None, typer.Option("--org", help="School code")] = None,
) -> None:
    """Safety-flagged student messages: ids, time and text (no names or usernames)."""
    rows = asyncio.run(_flagged(org))
    if not rows:
        typer.echo("No flagged messages.")
        return
    for r in rows:
        typer.echo(
            f"{r.org_code}  student {r.student_id}  thread {r.tutor_session_id}  "
            f"message {r.message_id}  {r.created_at:%Y-%m-%d %H:%M}Z\n    {r.text or '[purged]'}"
        )


async def _eval(runs: int, case_id: str | None) -> bool:
    from app.ai.client import DeepSeekTutorClient, make_chat_client
    from app.ai.eval import runner

    settings = get_settings()
    chat = make_chat_client()
    if chat is None:
        raise CliError("DEEPSEEK_API_KEY is not set.")
    cases = [c for c in runner.load_cases() if case_id is None or c.id == case_id]
    if not cases:
        raise CliError(f"No case {case_id}.")
    tutor_client = DeepSeekTutorClient(chat)
    # The judge model reasons longer than the tutor: its own client with a generous timeout.
    judge_client = make_chat_client(timeout=JUDGE_TIMEOUT_S)
    assert judge_client is not None
    totals = {
        "runs": 0,
        "leaks": 0,
        "steps": 0,
        "confirms": 0,
        "category": 0,
        "guard": 0,
        "errors": 0,
    }
    on_rung = helpful = 0
    t_in = t_out = j_in = j_out = 0
    ok = True
    typer.echo(f"{'case':<22} {'runs':>4} {'fail':>4} {'rung':>4} {'help':>4}  status / reason")
    try:
        async with get_sessionmaker()() as session:
            for case in cases:
                outcomes, ji, jo = await runner.run_case(
                    session,
                    case,
                    tutor_client,
                    judge_client,
                    settings.tutor_model,
                    settings.tutor_judge_model,
                    runs,
                )
                j_in, j_out = j_in + ji, j_out + jo
                fails = [o for o in outcomes if o.failed]
                ok = ok and not fails
                ok = ok and all(o.error is None for o in outcomes)
                for o in outcomes:
                    totals["runs"] += 1
                    if o.error is not None:
                        totals["errors"] += 1
                        continue
                    totals["leaks"] += o.verdict.leaks_answer
                    totals["steps"] += o.verdict.leaks_step
                    totals["confirms"] += o.verdict.confirms_correctness
                    totals["category"] += not o.category_ok
                    totals["guard"] += bool(o.guard_leaks)
                    on_rung += o.verdict.on_rung
                    helpful += o.verdict.helpful
                    t_in, t_out = t_in + o.tutor_in, t_out + o.tutor_out
                sample = (fails or outcomes)[0]
                note = f"{sample.status}/{sample.category}: {sample.verdict.reason}"
                typer.echo(
                    f"{case.id:<22} {len(outcomes):>4} {len(fails):>4} "
                    f"{sum(o.verdict.on_rung for o in outcomes):>4} "
                    f"{sum(o.verdict.helpful for o in outcomes):>4}  {note[:100]}"
                )
                errored = [o for o in outcomes if o.error is not None]
                if errored:
                    typer.echo(f"    unverified: {len(errored)} run(s): {errored[0].error}")
                if fails:
                    typer.echo(f"    reply: {sample.reply[:300]!r}")
                for o in outcomes:
                    if o.caught:
                        typer.echo(f"    guard caught ({o.status}): {'; '.join(o.caught)[:200]}")
    finally:
        await dispose_engine()
    n = max(1, totals["runs"])
    typer.echo(
        f"\nTotal {totals['runs']} runs: {totals['leaks']} answer leaks, {totals['steps']} step "
        f"leaks, {totals['confirms']} confirmations, {totals['category']} wrong categories, "
        f"{totals['guard']} guard hits on final replies, {totals['errors']} unverified runs. "
        f"on_rung {on_rung / n:.0%}, "
        f"helpful {helpful / n:.0%}."
    )
    typer.echo(
        f"Tokens: tutor {t_in} in (incl. cache hits) / {t_out} out, judge {j_in} in / {j_out} "
        "out. Cost: multiply by the provider's current prices."
    )
    return ok


JUDGE_TIMEOUT_S = 120.0


@tutor_app.command("eval")
def tutor_eval(
    runs: Annotated[int, typer.Option(help="Runs per case")] = 3,
    case: Annotated[str | None, typer.Option("--case", help="Only this case id")] = None,
) -> None:
    """Run the tutor leak eval against the real model (needs DEEPSEEK_API_KEY)."""
    try:
        ok = asyncio.run(_eval(runs, case))
    except CliError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("PASS" if ok else "FAIL")
    if not ok:
        raise typer.Exit(1)


def main() -> None:
    app()


async def _teacher_eval(runs: int, case_id: str | None) -> bool:
    from app.ai.client import make_chat_client
    from app.ai.eval import teacher_runner
    from app.ai.teacher_client import DeepSeekTeacherClient
    from app.ai.teacher_limits import TIMEOUT_S

    settings = get_settings()
    chat = make_chat_client(timeout=TIMEOUT_S)
    judge_client = make_chat_client(timeout=JUDGE_TIMEOUT_S)
    if chat is None or judge_client is None:
        raise CliError("DEEPSEEK_API_KEY is not set.")
    cases = [c for c in teacher_runner.load_cases() if case_id is None or c.id == case_id]
    if not cases:
        raise CliError(f"No case {case_id}.")
    writer = DeepSeekTeacherClient(chat)
    ok = True
    totals = {"runs": 0, "unsupported": 0, "overclaims": 0, "errors": 0, "no_claims": 0}
    vague = claims = notes = actionable = 0
    w_in = w_cached = w_out = j_in = j_out = 0
    typer.echo(f"{'case':<26} {'runs':>4} {'fail':>4} {'ok':>3} {'part':>4}  tokens in/out  notes")
    for tc in cases:
        outcomes = await teacher_runner.run_case(
            tc,
            writer,
            judge_client,
            settings.teacher_ai_model,
            settings.teacher_ai_judge_model,
            runs,
        )
        c_in = c_out = 0
        for o in outcomes:
            totals["runs"] += 1
            totals["errors"] += o.error is not None
            if o.result is not None:
                c_in += o.result.input_tokens + o.result.cache_read_tokens
                c_out += o.result.output_tokens
                w_cached += o.result.cache_read_tokens
                totals["no_claims"] += o.result.output is None or not o.result.output.summary
            if o.grades is not None:
                g = o.grades
                totals["unsupported"] += g.unsupported
                totals["overclaims"] += g.overclaims
                vague, claims = vague + g.vague, claims + g.claims
                notes, actionable = notes + g.notes, actionable + g.actionable
                j_in, j_out = j_in + g.input_tokens, j_out + g.output_tokens
        w_in, w_out = w_in + c_in, w_out + c_out
        fails = [o for o in outcomes if o.failed]
        ok = ok and not fails
        statuses = [o.result.status for o in outcomes if o.result is not None]
        typer.echo(
            f"{tc.id:<26} {len(outcomes):>4} {len(fails):>4} {statuses.count('ok'):>3} "
            f"{statuses.count('partial'):>4}  {c_in:>6}/{c_out:<6}"
        )
        for o in fails:
            typer.echo(f"    {o.error or '; '.join(o.problems)}")
            if o.grades and o.grades.reasons:
                typer.echo(f"    judge: {o.grades.reasons[0][:200]}")
    n_claims = max(1, claims)
    typer.echo(
        f"\nTotal {totals['runs']} runs: {totals['unsupported']} unsupported claims, "
        f"{totals['overclaims']} overclaimed causes, {totals['no_claims']} runs without a claim, "
        f"{totals['errors']} unverified runs. Vague quantities {vague / n_claims:.0%} of claims; "
        f"actionable notes {f'{actionable / notes:.0%}' if notes else 'n/a (no notes)'}."
    )
    typer.echo(
        f"Tokens: writer {w_in} in ({w_cached} cache hits) / {w_out} out, judge {j_in} in / "
        f"{j_out} out. Cost: multiply by the provider's current prices."
    )
    return ok


@teacher_ai_app.command("eval")
def teacher_ai_eval(
    runs: Annotated[int, typer.Option(help="Runs per case")] = 3,
    case: Annotated[str | None, typer.Option("--case", help="Only this case id")] = None,
) -> None:
    """Run the teacher-summary eval against the real model (needs DEEPSEEK_API_KEY; no DB)."""
    try:
        ok = asyncio.run(_teacher_eval(runs, case))
    except CliError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("PASS" if ok else "FAIL")
    if not ok:
        raise typer.Exit(1)
