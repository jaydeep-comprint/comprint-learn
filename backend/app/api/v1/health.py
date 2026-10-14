import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

HEALTH_DB_TIMEOUT_S = 3.0

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> HealthResponse:
    """API liveness plus a `SELECT 1` against the database. No auth, no tenant data."""
    try:
        async with asyncio.timeout(HEALTH_DB_TIMEOUT_S):
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        # Class name only: exception text can contain the host or credentials.
        logger.warning("Health check: database unreachable (%s)", type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="error", db="error")
    return HealthResponse(status="ok", db="ok")
