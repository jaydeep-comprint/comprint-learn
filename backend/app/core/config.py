"""App settings (env vars, then backend/.env) and database URL normalisation."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

MISSING_DATABASE_URL = (
    "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and fill it in."
)
BAD_SCHEME = "DATABASE_URL must be a postgres URL (postgresql://...)"

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
    environment: Literal["development", "test", "production"] = "development"
    cors_origins: Annotated[list[str], NoDecode] = []
    db_pool_size: int = 5
    db_max_overflow: int = 5

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, v: str) -> str:
        if v:
            normalize_db_url(v)
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def db_connection(self) -> tuple[str, dict[str, Any]]:
        """Normalised (url, connect_args) for `DATABASE_URL`."""
        return normalize_db_url(self.database_url)

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
