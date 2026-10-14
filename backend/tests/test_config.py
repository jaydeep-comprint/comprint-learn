import re

import pytest
from pydantic import ValidationError

from app.core.config import (
    BAD_SCHEME,
    MISSING_DATABASE_URL,
    Settings,
    get_settings,
    normalize_db_url,
)

REMOTE = "user:pw@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_postgres_schemes_become_asyncpg(scheme: str) -> None:
    url, _ = normalize_db_url(f"{scheme}://{REMOTE}")
    assert url == f"postgresql+asyncpg://{REMOTE}"


@pytest.mark.parametrize(
    "raw", ["mysql://u:p@h/db", "postgresql+psycopg://u:p@h/db", "sqlite:///x.db", "not a url"]
)
def test_other_schemes_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match=re.escape(BAD_SCHEME)):
        normalize_db_url(raw)


def test_remote_host_defaults_to_ssl_require() -> None:
    _, connect_args = normalize_db_url(f"postgresql://{REMOTE}")
    assert connect_args == {"ssl": "require"}


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_localhost_has_no_ssl_by_default(host: str) -> None:
    url, connect_args = normalize_db_url(f"postgresql://u:p@{host}:5432/db")
    assert url == f"postgresql+asyncpg://u:p@{host}:5432/db"
    assert connect_args == {}


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_sslmode_requiring_ssl_is_mapped(mode: str) -> None:
    url, connect_args = normalize_db_url(f"postgresql://u:p@localhost/db?sslmode={mode}")
    assert url == "postgresql+asyncpg://u:p@localhost/db"
    assert connect_args == {"ssl": "require"}


def test_sslmode_disable_means_no_ssl_even_for_remote_host() -> None:
    url, connect_args = normalize_db_url(f"postgresql://{REMOTE}?sslmode=disable")
    assert url == f"postgresql+asyncpg://{REMOTE}"
    assert connect_args == {}


def test_other_query_params_are_kept() -> None:
    url, connect_args = normalize_db_url(
        f"postgresql://{REMOTE}?application_name=api&sslmode=require&options=-c%20search_path%3Dx"
    )
    assert "sslmode" not in url
    assert "application_name=api" in url
    assert "options=" in url
    assert connect_args == {"ssl": "require"}


def test_encoded_password_is_not_decoded() -> None:
    raw = "postgresql://postgres.ref:p%40ss%23w%2Frd@aws-0-x.pooler.supabase.com:5432/postgres"
    url, _ = normalize_db_url(raw)
    assert url == raw.replace("postgresql://", "postgresql+asyncpg://", 1)


def test_settings_reject_bad_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://u:p@h/db")
    with pytest.raises(ValidationError, match=re.escape(BAD_SCHEME)):
        Settings()


def test_bad_url_error_does_not_echo_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://user:SuperSecretPw@host/db")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "SuperSecretPw" not in str(exc_info.value)


def test_missing_database_url_gives_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(RuntimeError) as exc_info:
        get_settings()
    assert str(exc_info.value) == MISSING_DATABASE_URL


def test_cors_origins_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.cors_origins == []
    assert (settings.db_pool_size, settings.db_max_overflow) == (5, 5)


def test_supabase_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co/")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    s = Settings()
    assert s.require_supabase_url() == "https://abc.supabase.co"
    assert s.supabase_jwt_secret is None
    assert s.require_service_role_key() == "test-service-role-key"
    assert "test-service-role-key" not in repr(s)


def test_missing_supabase_settings_raise_clear_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    s = Settings()
    with pytest.raises(RuntimeError, match="SUPABASE_URL is not set"):
        s.require_supabase_url()
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY is not set"):
        s.require_service_role_key()
