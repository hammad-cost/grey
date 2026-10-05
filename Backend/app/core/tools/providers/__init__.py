"""Search provider adapters. Each file implements SearchProvider for one vendor (or the mock)."""
from .mock_search import MockSearchProvider

__all__ = ["MockSearchProvider"]
