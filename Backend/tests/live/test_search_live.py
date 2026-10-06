"""
Live tests: a few real searches through SerpAPI and Tavily.

Each test uses one search credit, so they are SKIPPED unless you ask for them:

    $env:RUN_LIVE_SEARCH_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest -m live_search -s

They need SERPAPI_API_KEY and TAVILY_API_KEY in Backend/.env
(a test whose key is missing is skipped).
"""
import os

import pytest

from app.core.config.settings import Settings
from app.core.tools.factory import get_search_provider
from app.core.tools.providers.serpapi import SerpApiProvider
from app.core.tools.providers.tavily import TavilySearchProvider
from app.core.tools.search import SearchFocus, SearchQuery, SearchResult

pytestmark = [
    pytest.mark.live_search,
    pytest.mark.skipif(os.getenv("RUN_LIVE_SEARCH_TESTS") != "1", reason="set RUN_LIVE_SEARCH_TESTS=1 to call real search"),
]


def _key(name: str) -> str:
    key = getattr(Settings(), name).get_secret_value().strip()   # key comes from Backend/.env
    if not key:
        pytest.skip(f"{name.upper()} is not set in Backend/.env")
    return key


def _show(results: list[SearchResult]) -> None:
    for result in results:
        print(f"\n  [{result.provider}] {result.title}\n    {result.url}\n    publisher={result.publisher} date={result.published_date}")


@pytest.mark.parametrize("focus", [SearchFocus.GENERAL, SearchFocus.NEWS, SearchFocus.RESEARCH])
async def test_serpapi_returns_results(focus):
    provider = SerpApiProvider(_key("serpapi_api_key"))
    results = await provider.search(SearchQuery(text="fraud detection in banking", focus=focus, max_results=3))

    _show(results)
    assert 1 <= len(results) <= 3
    assert all(result.provider == "serpapi" for result in results)


async def test_site_search_only_returns_those_sites():
    # Google may ignore site: — SerpAPI then returns [] and the gateway asks Tavily.
    _key("serpapi_api_key")
    _key("tavily_api_key")
    gateway = get_search_provider(Settings(search_providers="serpapi,tavily"))
    results = await gateway.search(SearchQuery(
        text="fraud detection", include_domains=["ycombinator.com"], max_results=3,
    ))

    _show(results)
    assert results
    assert all("ycombinator.com" in result.url for result in results)


@pytest.mark.parametrize("focus", [SearchFocus.GENERAL, SearchFocus.NEWS])
async def test_tavily_returns_results(focus):
    provider = TavilySearchProvider(_key("tavily_api_key"))
    results = await provider.search(SearchQuery(text="fraud detection in banking", focus=focus, max_results=3, recency_days=365))

    _show(results)
    assert 1 <= len(results) <= 3
    assert all(result.provider == "tavily" for result in results)


async def test_gateway_from_settings_searches_for_real():
    _key("serpapi_api_key")
    gateway = get_search_provider(Settings(search_providers="serpapi,tavily"))
    results = await gateway.search(SearchQuery(text="hospital patient wait times", max_results=3))

    _show(results)
    assert results
    assert all(result.provider in {"serpapi", "tavily"} for result in results)


async def test_government_search_stays_on_government_sites():
    # Release 0.4.1: does Tavily accept bare endings like "gov" in include_domains?
    from app.domains.fyp.skills.research_evidence.sources import GOVERNMENT_SEARCH_SITES
    from app.core.tools.providers.common import on_sites

    provider = TavilySearchProvider(_key("tavily_api_key"))
    results = await provider.search(SearchQuery(
        text='"Clinical AI" Healthcare government initiative programme',
        focus=SearchFocus.GOVERNMENT, include_domains=GOVERNMENT_SEARCH_SITES, max_results=5,
    ))

    _show(results)
    assert results
    assert all(on_sites(result.url, GOVERNMENT_SEARCH_SITES) for result in results)


async def test_startup_directory_search_finds_directory_pages():
    # Release 0.4.1: the live run found only one startup list; Tavily now goes first,
    # and only directories with one page per startup are searched.
    from app.domains.fyp.skills.research_evidence.sources import STARTUP_PROFILE_SITES
    from app.domains.fyp.skills.research_evidence.startups import startup_names
    from app.core.tools.providers.common import on_sites

    _key("tavily_api_key")
    gateway = get_search_provider(Settings(search_providers="serpapi,tavily"))
    results = await gateway.search(SearchQuery(
        text='"Clinical AI" Healthcare startups', focus=SearchFocus.COMPANIES,
        include_domains=STARTUP_PROFILE_SITES, max_results=20,
    ))

    _show(results)
    names = startup_names(results, "Healthcare", "Clinical AI", limit=5)
    print("\n  startup names read:", names)
    assert all(on_sites(result.url, STARTUP_PROFILE_SITES) for result in results)
    assert len(names) >= 2
