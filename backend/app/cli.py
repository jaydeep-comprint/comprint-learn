"""Operator CLI: `uv run app org create|list` and `uv run app content check|import`."""

import asyncio
import re
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import case, func, select

from app.api.deps import OrgScope
from app.content.loader import ContentBundle, Issue, load
from app.content.validate import has_errors, validate
from app.core.errors import ApiProblem
from app.db.session import dispose_engine, get_sessionmaker
from app.models import AppUser, Organization, Role
from app.models.tenancy import SCHOOL_CODE_PATTERN
from app.services import tenancy
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

app = typer.Typer(no_args_is_help=True, add_completion=False)
org_app = typer.Typer(no_args_is_help=True, help="Schools (organizations).")
app.add_typer(org_app, name="org")
content_app = typer.Typer(no_args_is_help=True, help="Courses in content/ (validate, import).")
app.add_typer(content_app, name="content")

DEFAULT_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content"
RootOpt = Annotated[Path, typer.Option("--root", help="The content/ folder")]

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


def main() -> None:
    app()
