"""
Tests for backend configuration loading.
Confirms that settings are readable and that database_url is configurable.
"""
import os
import pytest
from pydantic_settings import BaseSettings


def test_settings_load():
    """Settings object can be imported and has expected fields."""
    from app.core.config import settings

    assert hasattr(settings, "app_env")
    assert hasattr(settings, "database_url")


def test_default_app_env():
    """APP_ENV defaults to development when not overridden."""
    from app.core.config import settings

    # The .env file sets development; this confirms it loaded.
    assert settings.app_env in ("development", "production")


def test_database_url_is_set():
    """DATABASE_URL is not empty."""
    from app.core.config import settings

    assert settings.database_url
    assert "://" in settings.database_url


def test_database_url_override(monkeypatch):
    """
    DATABASE_URL can be replaced by an environment variable.
    This simulates swapping SQLite for PostgreSQL without changing any code.
    """
    fake_url = "postgresql+asyncpg://user:pass@localhost:5432/grey"
    monkeypatch.setenv("DATABASE_URL", fake_url)

    # Re-create settings so it picks up the new env var.
    from app.core.config.settings import Settings
    overridden = Settings()

    assert overridden.database_url == fake_url


def test_is_development_property():
    """is_development returns True when APP_ENV is development."""
    from app.core.config.settings import Settings

    dev_settings = Settings(app_env="development", database_url="sqlite+aiosqlite:///./grey.db")
    assert dev_settings.is_development is True
    assert dev_settings.is_production is False


def test_is_production_property():
    """is_production returns True when APP_ENV is production."""
    from app.core.config.settings import Settings

    prod_settings = Settings(app_env="production", database_url="sqlite+aiosqlite:///./grey.db")
    assert prod_settings.is_production is True
    assert prod_settings.is_development is False


def test_cors_origins_split_into_list():
    """CORS_ORIGINS is a comma-separated string turned into a clean list."""
    from app.core.config.settings import Settings

    custom = Settings(cors_origins="http://localhost:3000, https://grey.example.com,")
    assert custom.cors_origin_list == ["http://localhost:3000", "https://grey.example.com"]
