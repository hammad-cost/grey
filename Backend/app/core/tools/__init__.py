"""
Tools: low-level, provider-independent operations used by skills.
Tools never know about students, workflows or the Project Brain.
"""
from .factory import SUPPORTED_SEARCH_PROVIDERS, get_search_provider
from .search import SearchFocus, SearchProvider, SearchProviderError, SearchQuery, SearchResult

__all__ = [
    "SUPPORTED_SEARCH_PROVIDERS",
    "SearchFocus",
    "SearchProvider",
    "SearchProviderError",
    "SearchQuery",
    "SearchResult",
    "get_search_provider",
]
