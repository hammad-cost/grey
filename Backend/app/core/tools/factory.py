"""
Builds the search tool named in settings (SEARCH_PROVIDERS in .env).

This is the only place that knows which provider classes exist.
Adding a vendor later = write its adapter in providers/, then add it to
_REAL_PROVIDERS below.

    SEARCH_PROVIDERS=mock            → MockSearchProvider (sample data)
    SEARCH_PROVIDERS=serpapi,tavily  → SearchGateway trying SerpAPI, then Tavily
"""
import logging
from collections.abc import Callable

from app.core.config.settings import Settings
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.providers.serpapi import SerpApiProvider
from app.core.tools.providers.tavily import TavilySearchProvider
from app.core.tools.search import SearchProvider
from app.core.tools.search_gateway import SearchGateway, SearchPolicy


def _serpapi(settings: Settings) -> SearchProvider | None:
    key = settings.serpapi_api_key.get_secret_value().strip()
    return SerpApiProvider(key, timeout_seconds=settings.search_timeout_seconds) if key else None


def _tavily(settings: Settings) -> SearchProvider | None:
    key = settings.tavily_api_key.get_secret_value().strip()
    return TavilySearchProvider(key, timeout_seconds=settings.search_timeout_seconds) if key else None


# Real providers: name → function that builds it from settings, or None if its
# key is missing (a provider without a key is simply skipped).
logger = logging.getLogger("grey.search")

_REAL_PROVIDERS: dict[str, Callable[[Settings], SearchProvider | None]] = {
    "serpapi": _serpapi,
    "tavily": _tavily,
}

SUPPORTED_SEARCH_PROVIDERS = ["mock", *_REAL_PROVIDERS]


def parse_search_providers(settings: Settings) -> list[str]:
    """
    The configured provider names, cleaned up and checked.

    Raises:
        ValueError: empty list, unknown name, a name listed twice, or "mock"
                    mixed with real providers (fake results must never
                    appear in live research).
    """
    names = [name.strip().lower() for name in settings.search_providers.split(",") if name.strip()]
    if not names:
        raise ValueError("SEARCH_PROVIDERS is empty. Use 'mock' or e.g. 'serpapi,tavily'.")
    for name in names:
        if name not in SUPPORTED_SEARCH_PROVIDERS:
            raise ValueError(
                f"Unknown search provider '{name}' in SEARCH_PROVIDERS. "
                f"Supported providers: {SUPPORTED_SEARCH_PROVIDERS}"
            )
    if len(set(names)) != len(names):
        raise ValueError("SEARCH_PROVIDERS lists the same provider twice.")
    if "mock" in names and len(names) > 1:
        raise ValueError("'mock' can't be combined with real search providers in SEARCH_PROVIDERS.")
    return names


def search_provider_label(settings: Settings) -> str:
    """A short label for the research run record, e.g. "mock" or "serpapi,tavily"."""
    return ",".join(parse_search_providers(settings))


def get_search_provider(settings: Settings) -> SearchProvider:
    """Build the search tool configured in settings."""
    names = parse_search_providers(settings)
    if names == ["mock"]:
        return MockSearchProvider(delay_ms=settings.mock_search_delay_ms)

    providers = [p for name in names if (p := _REAL_PROVIDERS[name](settings)) is not None]
    missing = [name for name in names if name not in {p.name for p in providers}]
    if missing:
        # Say it clearly at startup; otherwise every research run would just fail later.
        logger.warning(
            "SEARCH_PROVIDERS lists %s but no API key is set for it — skipped. "
            "Add the key(s) to Backend/.env.%s",
            ", ".join(missing),
            " No search provider is usable: research will fail until a key is added." if not providers else "",
        )
    policy = SearchPolicy(
        timeout_seconds=settings.search_timeout_seconds,
        max_retries=settings.search_max_retries,
        cooldown_seconds=settings.search_cooldown_seconds,
        quota_cooldown_seconds=settings.search_quota_cooldown_seconds,
    )
    return SearchGateway(providers, policy)
