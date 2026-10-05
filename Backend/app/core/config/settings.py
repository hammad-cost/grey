from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Grey application settings.

    Values are loaded from the .env file automatically.
    Any value can also be overridden by setting the environment variable
    directly in the shell — useful in CI/CD and production deployments.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"

    # ── Database ──────────────────────────────────────────────────────────────
    # The full SQLAlchemy connection string.
    # SQLite  → sqlite+aiosqlite:///./grey.db
    # Postgres → postgresql+asyncpg://user:password@host:5432/grey
    # Only this line changes when swapping databases — nothing else in the
    # codebase needs to know which database engine is being used.
    database_url: str = "sqlite+aiosqlite:///./grey.db"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Browser origins allowed to call this API, separated by commas.
    # The Next.js frontend runs on http://localhost:3000 during development.
    cors_origins: str = "http://localhost:3000"

    # ── Search tool ───────────────────────────────────────────────────────────
    # Which search provider evidence research uses. Release 0.2 supports "mock" only.
    search_provider: str = "mock"
    # Pause (milliseconds) per mock search, so research progress is visible in the UI.
    mock_search_delay_ms: int = 400

    @property
    def cors_origin_list(self) -> list[str]:
        """cors_origins split into a clean list, e.g. ["http://localhost:3000"]."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


# Single shared instance — import this everywhere instead of creating new ones.
settings = Settings()
