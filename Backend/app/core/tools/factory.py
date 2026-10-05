"""
Picks the search provider named in settings (SEARCH_PROVIDER in .env).

This is the only place that knows which provider classes exist.
Adding a vendor later = write its adapter in providers/, then add one line here.
"""
from app.core.config.settings import Settings
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import SearchProvider

SUPPORTED_SEARCH_PROVIDERS = ["mock"]


def get_search_provider(settings: Settings) -> SearchProvider:
    """
    Build the search provider configured in settings.

    Raises:
        ValueError: if SEARCH_PROVIDER names a provider that doesn't exist.
    """
    name = settings.search_provider.strip().lower()

    if name == "mock":
        return MockSearchProvider(delay_ms=settings.mock_search_delay_ms)

    raise ValueError(
        f"Unknown SEARCH_PROVIDER '{settings.search_provider}'. "
        f"Supported providers: {SUPPORTED_SEARCH_PROVIDERS}"
    )
