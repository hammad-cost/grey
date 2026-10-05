"""
Search tool — the provider-independent interface every web search goes through.

A Tool is a narrow, low-level operation. This one only answers:
"given a search query, what pages did you find?"

It knows nothing about students, FYPs, industries, workflows or evidence
tiers — that reasoning belongs to skills (e.g. ResearchEvidenceSkill).

Vendors (Tavily, Brave, Exa, …) are plugged in by writing one adapter class
in core/tools/providers/ that implements SearchProvider. Skills only ever
see SearchProvider, so swapping vendors does not change any skill.
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


class SearchProviderError(Exception):
    """Raised when a provider cannot complete a search (network error, quota, bad key, …)."""


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

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """
        Run one search and return at most query.max_results results.

        Raises:
            SearchProviderError: if the search could not be completed.
        """
        ...
