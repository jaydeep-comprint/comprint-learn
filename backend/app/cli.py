"""Operator CLI: `uv run app org create ...` and `uv run app org list`.

Spec 003 adds `app content ...` subcommands.
"""

import asyncio
import re
from typing import Annotated

import typer
from sqlalchemy import case, func, select

from app.api.deps import OrgScope
from app.core.errors import ApiProblem
from app.db.session import dispose_engine, get_sessionmaker
from app.models import AppUser, Organization, Role
from app.models.tenancy import SCHOOL_CODE_PATTERN
from app.services import tenancy
from app.services.supabase_admin import SupabaseAdmin, get_supabase_admin

app = typer.Typer(no_args_is_help=True, add_completion=False)
org_app = typer.Typer(no_args_is_help=True, help="Schools (organizations).")
app.add_typer(org_app, name="org")

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
            return [(c, n, t, st) for c, n, t, st in (await session.execute(stmt)).tuples()]
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


def main() -> None:
    app()
