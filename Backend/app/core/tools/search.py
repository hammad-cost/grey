"""
Search tool — the provider-independent interface every web search goes through.

A Tool is a narrow, low-level operation. This one only answers:
"given a search query, what pages did you find?"

It knows nothing about students, FYPs, industries, workflows or evidence
tiers — that reasoning belongs to skills (e.g. ResearchEvidenceSkill).

Vendors (SerpAPI, Tavily, …) are plugged in by writing one adapter class
in core/tools/providers/ that implements SearchProvider. Skills only ever
see SearchProvider, so swapping vendors does not change any skill.

When several vendors are configured, SearchGateway (search_gateway.py) tries
them in order and falls back when one is rate-limited, out of credits or down.
"""
from abc import ABC, abstractmethod
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class SearchFocus(str, Enum):
    """
    An optional hint about what kind of pages are wanted.

    Many search APIs support a filter like this (e.g. "news" or "research paper").
    Providers that don't support a focus simply ignore it.
    """
    GENERAL = "general"
    COMPANIES = "companies"      # company and startup websites
    GOVERNMENT = "government"    # government initiatives, reports, programmes
    RESEARCH = "research"        # papers and university research
    DATASETS = "datasets"        # public dataset pages
    NEWS = "news"


class SearchQuery(BaseModel):
    """What to search for."""
    text: str = Field(min_length=1)                 # e.g. '"Fraud Detection" Finance startups'
    focus: SearchFocus = SearchFocus.GENERAL
    max_results: int = Field(default=5, ge=1, le=20)
    # Only return pages from these sites, e.g. ["ycombinator.com", "producthunt.com"].
    # Empty = the whole web. Providers apply it their own way (site: filters, domain lists).
    include_domains: list[str] = []
    # Prefer pages from roughly the last N days (None = any time). Best effort.
    recency_days: int | None = Field(default=None, ge=1)


class SearchResult(BaseModel):
    """
    One page a provider found — raw and vendor-neutral.

    These are only the fields real search APIs commonly return.
    Turning a result into Project Brain evidence (tier, problem, insight, …)
    is the job of a skill, not of the tool.
    """
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://\S+$")
    snippet: str = Field(min_length=1)              # short text from the page
    publisher: str | None = None                    # site or organization name, if known
    published_date: date | None = None              # if the provider knows it
    provider: str | None = None                     # which search service found it, e.g. "serpapi"


# ── Errors ────────────────────────────────────────────────────────────────────
# Adapters translate every vendor failure into one of these, so the gateway can
# decide what to do without knowing the vendor. Same idea as core/llm/errors.py.

class SearchProviderError(Exception):
    """Base class: a provider could not complete a search."""

    kind = "search_error"
    retryable = False           # worth trying the same provider again?

    def __init__(self, message: str = "", *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class SearchRateLimited(SearchProviderError):
    """Too many searches right now (e.g. HTTP 429). Wait, retry, then fall back."""

    kind = "rate_limited"
    retryable = True

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class SearchTimeout(SearchProviderError):
    """The provider didn't answer in time. Retry, then fall back."""

    kind = "timeout"
    retryable = True


class SearchServerError(SearchProviderError):
    """The provider failed on its side (5xx, connection dropped). Retry, then fall back."""

    kind = "server_error"
    retryable = True


class SearchQuotaExhausted(SearchProviderError):
    """The plan's searches/credits are used up. Retrying won't help; fall back."""

    kind = "quota_exhausted"


class SearchAuthError(SearchProviderError):
    """The API key is missing or wrong. The provider is unusable; fall back."""

    kind = "auth_error"


class SearchBadRequest(SearchProviderError):
    """The provider rejected this request (e.g. an unsupported filter). Fall back."""

    kind = "bad_request"


class SearchUnavailable(SearchProviderError):
    """No configured provider could complete the search."""

    kind = "unavailable"

    def __init__(self, message: str = "", *, causes: list[str] | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.causes = causes or []


class SearchProvider(ABC):
    """
    The contract every search provider must follow.

    Subclass this to add a vendor:

        class TavilySearchProvider(SearchProvider):
            name = "tavily"

            async def search(self, query: SearchQuery) -> list[SearchResult]:
                ...  # call the Tavily API, convert its response to SearchResult objects
    """

    # Short identifier saved with every piece of evidence, e.g. "mock" or "tavily".
    name: str

    def keeps_to_sites(self, query: SearchQuery) -> bool:
        """
        True if this provider reliably returns only query.include_domains sites
        for this query. The gateway asks such providers first for site-limited
        searches. Default: no (most web search engines treat sites as a hint).
        """
        return False

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """
        Run one search and return at most query.max_results results.

        Raises:
            SearchProviderError: if the search could not be completed.
        """
        ...
