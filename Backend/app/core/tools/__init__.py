"""
Tools: low-level, provider-independent operations used by skills.
Tools never know about students, workflows or the Project Brain.
"""
from .factory import (
    SUPPORTED_SEARCH_PROVIDERS,
    get_search_provider,
    parse_search_providers,
    search_provider_label,
)
from .search import (
    SearchAuthError,
    SearchBadRequest,
    SearchFocus,
    SearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchQuotaExhausted,
    SearchRateLimited,
    SearchResult,
    SearchServerError,
    SearchTimeout,
    SearchUnavailable,
)
from .search_gateway import SearchGateway, SearchPolicy

__all__ = [
    "SUPPORTED_SEARCH_PROVIDERS",
    "SearchAuthError",
    "SearchBadRequest",
    "SearchFocus",
    "SearchGateway",
    "SearchPolicy",
    "SearchProvider",
    "SearchProviderError",
    "SearchQuery",
    "SearchQuotaExhausted",
    "SearchRateLimited",
    "SearchResult",
    "SearchServerError",
    "SearchTimeout",
    "SearchUnavailable",
    "get_search_provider",
    "parse_search_providers",
    "search_provider_label",
]
