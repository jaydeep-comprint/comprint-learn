"""Spec 015 security review, area 3: who may call each API route.

Walks every route (FastAPI 0.143 nests routers: `iter_route_contexts`) and prints a Markdown table
of method, path, the role its dependencies require (public, signed in with a temp password
allowed, signed in, student, staff, admin) and whether it goes through `OrgScope`.
Run: `cd backend && uv run python ../scripts/route_roles.py` (the development app, so the debug
route is listed too).
"""

import inspect
import os
from collections.abc import Callable, Iterator
from typing import Any

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost:5432/x")

from fastapi.dependencies.models import Dependant  # noqa: E402
from fastapi.routing import iter_route_contexts  # noqa: E402

from app.api import deps  # noqa: E402
from app.main import create_app  # noqa: E402

LEVELS: list[tuple[str, Callable[..., Any]]] = [
    ("admin", deps.require_admin),
    ("staff", deps.require_staff),
    ("student", deps.require_student),
    ("signed in", deps.get_current_user),
    ("signed in (temp password ok)", deps.get_current_user_allow_password_change),
]


def calls(dep: Dependant) -> Iterator[Callable[..., Any]]:
    for sub in dep.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from calls(sub)


def builds_scope(fn: Callable[..., Any]) -> bool:
    try:
        return inspect.signature(fn).return_annotation in (deps.OrgScope, "OrgScope")
    except (TypeError, ValueError):
        return False


def main() -> None:
    rows = []
    for ctx in iter_route_contexts(create_app().routes):
        dependant = getattr(ctx, "dependant", None)
        path = ctx.path_format
        if not isinstance(dependant, Dependant) or not path or not path.startswith("/api/"):
            continue
        found = set(calls(dependant))
        role = next((name for name, fn in LEVELS if fn in found), "public")
        scoped = "yes" if any(builds_scope(c) for c in found) else "no"
        for method in sorted(ctx.methods or ()):
            rows.append((path, method, role, scoped))
    print("| Method | Path | Requires | OrgScope |")
    print("|---|---|---|---|")
    for path, method, role, scoped in sorted(rows):
        print(f"| {method} | `{path}` | {role} | {scoped} |")
    print(f"\n{len(rows)} routes.")


if __name__ == "__main__":
    main()
