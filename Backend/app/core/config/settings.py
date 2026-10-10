from pydantic import SecretStr
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
    # Which search providers evidence research uses, in fallback order.
    #   "mock"           → sample results, no key, no cost (default; used by tests)
    #   "serpapi,tavily" → real web search: SerpAPI first, Tavily if it can't answer
    # "mock" can't be mixed with real providers, so fake results never appear in live research.
    search_providers: str = "mock"
    # Pause (milliseconds) per mock search, so research progress is visible in the UI.
    mock_search_delay_ms: int = 400

    # Real search provider keys. A provider without a key is skipped. Never commit real keys.
    serpapi_api_key: SecretStr = SecretStr("")
    tavily_api_key: SecretStr = SecretStr("")

    # Most searches one research run may make (free search plans are small).
    research_max_searches: int = 15
    # Most searches one dataset search may make (Release 0.8).
    dataset_max_searches: int = 6

    # Limits for every real search (see app/core/tools/search_gateway.py).
    search_timeout_seconds: float = 20.0
    search_max_retries: int = 2
    search_cooldown_seconds: float = 60.0           # skip a provider this long after rate limits / errors
    search_quota_cooldown_seconds: float = 3600.0   # skip a provider this long after its credits run out

    # ── LLM (Release 0.3) ─────────────────────────────────────────────────────
    # fake = every model call is answered by FakeLLMProvider (no key, no cost).
    # live = use the real providers in the profile routes below.
    llm_mode: str = "fake"

    # Provider keys. A provider without a key is skipped. Never commit real keys.
    groq_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Optional per-profile overrides: ordered "provider:model" routes, comma-separated.
    # Empty = use the defaults in app/core/llm/profiles.py.
    llm_profile_fast_cheap: str = ""
    llm_profile_structured_reasoning: str = ""
    llm_profile_high_quality_reasoning: str = ""
    llm_profile_writing: str = ""
    llm_profile_long_context: str = ""

    # Limits for every model call (see app/core/llm/gateway.py).
    llm_timeout_seconds: float = 60.0           # one attempt
    llm_total_deadline_seconds: float = 150.0   # all retries and fallbacks together
    llm_max_retries: int = 2                    # extra tries per model for short-lived failures
    llm_cooldown_seconds: float = 60.0          # skip a model this long after rate limits / errors
    llm_quota_cooldown_seconds: float = 3600.0  # skip a model this long after a daily/quota limit

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
