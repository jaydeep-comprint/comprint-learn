import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.db.session import dispose_engine

logger = logging.getLogger(__name__)

TRANSACTION_POOLER_PORT = 6543


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.db_port() == TRANSACTION_POOLER_PORT:
        logger.warning(
            "DATABASE_URL uses port 6543 (Supabase Transaction pooler), which breaks asyncpg "
            "prepared statements: use the Session pooler, port 5432"
        )
    yield
    await dispose_engine()


async def _api_problem_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiProblem)
    body = {"code": exc.code, "message": exc.message or exc.code}
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    return JSONResponse(body, status_code=exc.status, headers=headers)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Learning App API", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_exception_handler(ApiProblem, _api_problem_handler)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
