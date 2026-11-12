"""App settings (env vars, then backend/.env) and database URL normalisation."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

MISSING_DATABASE_URL = (
    "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and fill it in."
)
BAD_SCHEME = "DATABASE_URL must be a postgres URL (postgresql://...)"
MISSING_SUPABASE_URL = "SUPABASE_URL is not set. Add it to backend/.env (see backend/.env.example)."
MISSING_SERVICE_ROLE_KEY = (
    "SUPABASE_SERVICE_ROLE_KEY is not set. Add it to backend/.env (see backend/.env.example)."
)

_ASYNC_SCHEME = "postgresql+asyncpg"
_SCHEME_MAP = {"postgres": _ASYNC_SCHEME, "postgresql": _ASYNC_SCHEME, _ASYNC_SCHEME: _ASYNC_SCHEME}
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def normalize_db_url(raw: str) -> tuple[str, dict[str, Any]]:
    """Turn a Postgres URL into an asyncpg SQLAlchemy URL plus `connect_args`.

    Works on the raw string so the (percent-encoded) password is never decoded or re-encoded.
    """
    scheme, sep, rest = raw.strip().partition("://")
    if not sep or scheme.lower() not in _SCHEME_MAP:
        raise ValueError(BAD_SCHEME)

    parts = urlsplit(f"{_ASYNC_SCHEME}://{rest}")
    params = parse_qsl(parts.query, keep_blank_values=True)
    sslmode = next((v for k, v in params if k == "sslmode"), None)
    kept = [(k, v) for k, v in params if k != "sslmode"]

    connect_args: dict[str, Any] = {}
    if sslmode is None:
        if (parts.hostname or "") not in _LOCAL_HOSTS:
            connect_args["ssl"] = "require"
    elif sslmode == "require" or sslmode.startswith("verify-"):
        connect_args["ssl"] = "require"
    # sslmode=disable (or allow/prefer): no SSL forced.

    url = f"{_ASYNC_SCHEME}://{parts.netloc}{parts.path}"
    if kept:
        url += f"?{urlencode(kept)}"
    if parts.fragment:
        url += f"#{parts.fragment}"
    return url, connect_args


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo DATABASE_URL (it contains the password).
        hide_input_in_errors=True,
    )

    database_url: str = ""
    test_database_url: str | None = None
    supabase_url: str | None = None
    # Secret: bypasses Supabase RLS and can manage auth users. Never log it.
    supabase_service_role_key: SecretStr | None = None
    # Legacy projects only: HS256 shared secret. Unset = verify with the project's JWKS.
    supabase_jwt_secret: SecretStr | None = None
    # Public URL of the web app, used for invite / password-reset redirects.
    app_url: str = "http://localhost:5173"
    environment: Literal["development", "test", "production"] = "development"
    cors_origins: Annotated[list[str], NoDecode] = []
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # AI tutor (spec 009), on DeepSeek's OpenAI-compatible API (decided Nov 2026). Secret: never
    # log the key. Unset key or TUTOR_ENABLED=false = tutor off.
    deepseek_api_key: SecretStr | None = None
    tutor_enabled: bool = True
    tutor_base_url: str = "https://api.deepseek.com"
    tutor_model: str = "deepseek-flash"
    tutor_judge_model: str = "deepseek-v4-pro"  # eval only
    # Teacher AI summaries (spec 011): same provider and key as the tutor, its own kill switch.
    teacher_ai_enabled: bool = True
    teacher_ai_model: str = "deepseek-v4-pro"
    teacher_ai_judge_model: str = "deepseek-v4-pro"  # eval only
    # Spec 015: error tracking. Unset = Sentry is never initialised (always in tests).
    sentry_dsn: SecretStr | None = None
    git_sha: str | None = None  # Sentry `release`, set by the deploy
    # Spec 015: per-user rate limits (app/core/ratelimit.py). Off in unit tests.
    rate_limit_enabled: bool = True
    rate_limit_write_per_min: int = 120
    rate_limit_write_burst: int = 40
    rate_limit_read_per_min: int = 600
    rate_limit_read_burst: int = 120
    # Proxies in front of the API that append to X-Forwarded-For. 0 = use the socket address.
    trusted_proxy_count: int = 0
    # The per-request access log line (always on in production; the load test turns it on).
    access_log: bool = False

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, v: str) -> str:
        if v:
            normalize_db_url(v)
        return v

    @field_validator(
        "supabase_service_role_key",
        "supabase_jwt_secret",
        "deepseek_api_key",
        "sentry_dsn",
        "git_sha",
        mode="before",
    )
    @classmethod
    def _empty_secret_is_unset(cls, v: object) -> object:
        return None if v == "" else v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def db_connection(self) -> tuple[str, dict[str, Any]]:
        """Normalised (url, connect_args) for `DATABASE_URL`."""
        return normalize_db_url(self.database_url)

    def require_supabase_url(self) -> str:
        """`SUPABASE_URL` without a trailing slash; raises if unset (checked only when used)."""
        if not self.supabase_url:
            raise RuntimeError(MISSING_SUPABASE_URL)
        return self.supabase_url.rstrip("/")

    def require_service_role_key(self) -> str:
        if self.supabase_service_role_key is None:
            raise RuntimeError(MISSING_SERVICE_ROLE_KEY)
        return self.supabase_service_role_key.get_secret_value()

    @property
    def tutor_available(self) -> bool:
        return self.tutor_enabled and self.deepseek_api_key is not None

    @property
    def teacher_ai_available(self) -> bool:
        """Independent of `tutor_enabled`: only the shared key is common."""
        return self.teacher_ai_enabled and self.deepseek_api_key is not None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_problems(self) -> list[str]:
        """Settings a production API must not start with (checked by `create_app` only, so CLI
        commands are unaffected). Empty CORS_ORIGINS stays valid (a same-origin deployment)."""
        if not self.is_production:
            return []
        problems = []
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must not contain '*' in production")
        if not self.app_url.startswith("https://"):
            problems.append("APP_URL must be an https:// URL in production")
        return problems

    def db_port(self) -> int | None:
        try:
            return urlsplit(self.database_url).port
        except ValueError:  # non-numeric port: connecting will report it
            return None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.database_url:
        raise RuntimeError(MISSING_DATABASE_URL)
    return settings
