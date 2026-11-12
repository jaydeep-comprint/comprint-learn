"""Development-only routes (spec 015), included by `create_app` only in development."""

from fastapi import APIRouter

from app.api.deps import Scope

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/boom")
async def boom(_scope: Scope) -> None:
    """Raise an unhandled error, to check the 500 shape, the toast code and Sentry."""
    raise RuntimeError("debug boom (spec 015 smoke test)")
