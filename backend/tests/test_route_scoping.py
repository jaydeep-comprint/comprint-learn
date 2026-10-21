"""Guards the choke point: every API route authenticates, and tenant routes go through OrgScope.

Fails naming the route, so a new endpoint can't forget either.
"""

import inspect
from collections.abc import Callable, Iterator
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts

from app.api.deps import (
    OrgScope,
    get_current_user,
    get_current_user_allow_password_change,
)
from app.main import create_app

PUBLIC = {("GET", "/api/v1/health")}
# Routes allowed to skip the must_change_password check (and so `get_current_user`).
PASSWORD_CHANGE_ALLOWED = {("GET", "/api/v1/me"), ("POST", "/api/v1/me/password")}
# Routes that authenticate but read only global (platform-owned) content, so skip OrgScope.
GLOBAL_CONTENT = {("GET", "/api/v1/courses"), ("GET", "/api/v1/courses/{slug}/graph")}


def _calls(dep: Dependant) -> Iterator[Callable[..., Any]]:
    for sub in dep.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _calls(sub)


def _routes() -> Iterator[tuple[str, str, Dependant]]:
    """(method, path, dependant) for every API route, flattened the way OpenAPI sees them."""
    for ctx in iter_route_contexts(create_app().routes):
        path, dependant = ctx.path_format, getattr(ctx, "dependant", None)
        if path and path.startswith("/api/v1") and isinstance(dependant, Dependant):
            for method in sorted(ctx.methods or ()):
                yield method, path, dependant


def _builds_scope(call: Callable[..., Any]) -> bool:
    return inspect.signature(call).return_annotation in (OrgScope, "OrgScope")


def test_every_route_authenticates() -> None:
    missing = []
    for method, path, route in _routes():
        if (method, path) in PUBLIC:
            continue
        calls = set(_calls(route))
        if (method, path) in PASSWORD_CHANGE_ALLOWED:
            ok = get_current_user_allow_password_change in calls
        else:
            ok = get_current_user in calls
        if not ok:
            missing.append(f"{method} {path}")
    assert not missing, f"Routes without the auth dependency: {missing}"


def test_only_allowlisted_routes_skip_password_change_check() -> None:
    offenders = []
    for method, path, route in _routes():
        if (method, path) in PUBLIC:
            continue
        calls = set(_calls(route))
        skips_check = get_current_user not in calls
        if skips_check and (method, path) not in PASSWORD_CHANGE_ALLOWED:
            offenders.append(f"{method} {path}")
    assert not offenders, f"Routes that let temp-password users through: {offenders}"


def test_routes_with_tenant_ids_use_org_scope() -> None:
    missing = []
    for method, path, route in _routes():
        if (method, path) in PUBLIC | PASSWORD_CHANGE_ALLOWED | GLOBAL_CONTENT:
            continue
        if not any(_builds_scope(c) for c in _calls(route)):
            missing.append(f"{method} {path}")
    assert not missing, f"Routes not using OrgScope: {missing}"


def test_walker_sees_the_routes() -> None:
    paths = {p for _, p, _ in _routes()}
    assert "/api/v1/classes/{class_id}/enrollments/{student_id}" in paths
    assert len(paths) >= 12


def test_global_content_routes_exist_and_skip_scope() -> None:
    routes = {(m, p): r for m, p, r in _routes()}
    for key in GLOBAL_CONTENT:
        assert key in routes, key
        assert not any(_builds_scope(c) for c in _calls(routes[key])), key
