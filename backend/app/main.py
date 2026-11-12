import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.core.middleware import (
    BodyCapMiddleware,
    CatchAllMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.observability import capture_exception, configure_logging, init_sentry
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
    body = {**exc.extra, "code": exc.code, "message": exc.message or exc.code}
    headers = dict(exc.headers)
    if exc.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if exc.status >= 500:
        # 502/503 from a Supabase or DeepSeek outage: one Sentry issue per code, not thousands.
        capture_exception(exc, fingerprint=["api-problem", exc.code])
    return JSONResponse(body, status_code=exc.status, headers=headers or None)


async def _validation_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422 shape without `input`: it echoed passwords and pasted lists of children's
    names back in the body (spec 015 security review, area 10)."""
    assert isinstance(exc, RequestValidationError)
    detail = [{k: v for k, v in err.items() if k not in ("input", "url")} for err in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(detail)}, status_code=422)


def create_app() -> FastAPI:
    settings = get_settings()
    problems = settings.production_problems()
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))
    configure_logging(settings)
    init_sentry(settings)
    docs = not settings.is_production
    app = FastAPI(
        title="Learning App API",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    # Starlette wraps in reverse: the last added is the outermost.
    app.add_middleware(CatchAllMiddleware)
    app.add_middleware(BodyCapMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            # Bearer tokens, no cookies: credentialed CORS isn't needed (review area 10).
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            # Spec 014: the export's filename, when the SPA is on another origin.
            expose_headers=["Content-Disposition", "X-Request-ID", "Retry-After"],
        )
    app.add_middleware(
        RequestIdMiddleware, access_log_enabled=settings.is_production or settings.access_log
    )
    app.add_exception_handler(ApiProblem, _api_problem_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.include_router(api_router, prefix="/api/v1")
    if settings.environment == "development":
        from app.api.v1 import debug

        app.include_router(debug.router, prefix="/api/v1")
    return app


app = create_app()
