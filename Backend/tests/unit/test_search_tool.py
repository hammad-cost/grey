"""
Tests for the provider-independent search tool and the mock provider.
"""
import time
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError

from app.core.config.settings import Settings
from app.core.tools import parse_search_providers, search_provider_label
from app.core.tools import (
    SUPPORTED_SEARCH_PROVIDERS,
    SearchFocus,
    SearchProvider,
    SearchQuery,
    SearchResult,
    get_search_provider,
)
from app.core.tools.providers.mock_search import MockSearchProvider


@pytest.fixture
def mock() -> MockSearchProvider:
    return MockSearchProvider(delay_ms=0)


def hosts(results: list[SearchResult]) -> list[str]:
    return [urlparse(r.url).hostname for r in results]


# ── The interface ─────────────────────────────────────────────────────────────

def test_search_provider_cannot_be_used_without_implementing_search():
    with pytest.raises(TypeError):
        SearchProvider()


def test_search_query_defaults():
    query = SearchQuery(text="anything")
    assert query.focus == SearchFocus.GENERAL
    assert query.max_results == 5


@pytest.mark.parametrize("bad", [dict(text=""), dict(text="x", max_results=0),
                                 dict(text="x", max_results=21), dict(text="x", focus="cats")])
def test_search_query_rejects_invalid_values(bad):
    with pytest.raises(ValidationError):
        SearchQuery(**bad)


def test_search_result_requires_a_real_looking_url_and_text():
    with pytest.raises(ValidationError):
        SearchResult(title="t", url="not-a-url", snippet="s")
    with pytest.raises(ValidationError):
        SearchResult(title="t", url="https://a.example", snippet="")


def test_search_result_publisher_and_date_are_optional():
    result = SearchResult(title="t", url="https://a.example/x", snippet="s")
    assert result.publisher is None and result.published_date is None


# ── Mock provider ─────────────────────────────────────────────────────────────

async def test_mock_is_named_mock(mock):
    assert mock.name == "mock"
    assert isinstance(mock, SearchProvider)


async def test_mock_returns_valid_structured_results(mock):
    results = await mock.search(SearchQuery(text='"Fraud Detection" Finance', focus=SearchFocus.COMPANIES))

    assert results
    for r in results:
        assert isinstance(r, SearchResult)
        assert r.title and r.snippet and r.publisher
        # Snippets read like real ones: a problem sentence, then an insight sentence.
        assert r.snippet.count(". ") >= 1


async def test_mock_is_deterministic(mock):
    query = SearchQuery(text='"Navy" Defense', focus=SearchFocus.GOVERNMENT)
    assert await mock.search(query) == await mock.search(query)


async def test_mock_uses_the_quoted_phrase_as_topic(mock):
    results = await mock.search(SearchQuery(text='"Precision Farming" Agriculture initiatives',
                                            focus=SearchFocus.GOVERNMENT))
    assert all("Precision Farming" in r.title + r.snippet for r in results)
    assert all("precision-farming" in r.url for r in results)


async def test_mock_uses_whole_query_when_nothing_is_quoted(mock):
    [result] = await mock.search(SearchQuery(text="Smart Grids", focus=SearchFocus.NEWS, max_results=1))
    assert "Smart Grids" in result.title


async def test_mock_results_change_with_the_topic(mock):
    navy = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.RESEARCH))
    banking = await mock.search(SearchQuery(text='"Banking"', focus=SearchFocus.RESEARCH))
    assert [r.title for r in navy] != [r.title for r in banking]


async def test_mock_respects_max_results(mock):
    for n in (1, 2, 3):
        results = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.GENERAL, max_results=n))
        assert len(results) == n


async def test_mock_never_returns_more_than_it_has(mock):
    results = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.DATASETS, max_results=20))
    assert 0 < len(results) <= 20


async def test_mock_urls_can_never_point_at_real_websites(mock):
    """Every mock URL uses the reserved .example top-level domain (RFC 2606)."""
    for focus in SearchFocus:
        results = await mock.search(SearchQuery(text='"Navy"', focus=focus, max_results=20))
        assert all(host.endswith(".example") for host in hosts(results)), focus


async def test_mock_focus_changes_the_kind_of_source(mock):
    gov = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.GOVERNMENT))
    research = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.RESEARCH))

    assert all(".gov." in h for h in hosts(gov))
    assert not any(".gov." in h for h in hosts(research))


async def test_mock_general_search_mixes_kinds_of_source(mock):
    results = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.GENERAL, max_results=5))
    # One from companies, government, research, news and datasets → 5 different hosts.
    assert len(set(hosts(results))) == 5


async def test_mock_results_have_unique_urls(mock):
    for focus in SearchFocus:
        results = await mock.search(SearchQuery(text='"Navy"', focus=focus, max_results=20))
        assert len({r.url for r in results}) == len(results)


async def test_mock_includes_some_undated_results(mock):
    """Real search results don't always have a date; the mock mirrors that."""
    results = await mock.search(SearchQuery(text='"Navy"', focus=SearchFocus.GENERAL, max_results=20))
    dated = [r for r in results if r.published_date]
    assert 0 < len(dated) < len(results)


async def test_mock_delay_is_applied():
    slow = MockSearchProvider(delay_ms=50)
    start = time.perf_counter()
    await slow.search(SearchQuery(text="x"))
    assert time.perf_counter() - start >= 0.04


# ── Factory and settings ──────────────────────────────────────────────────────

def test_settings_default_to_mock_provider():
    settings = Settings(_env_file=None)
    assert settings.search_providers == "mock"
    assert settings.mock_search_delay_ms == 400


def test_factory_builds_mock_provider_from_settings():
    provider = get_search_provider(Settings(_env_file=None, search_providers="mock", mock_search_delay_ms=0))
    assert isinstance(provider, MockSearchProvider)
    assert "mock" in SUPPORTED_SEARCH_PROVIDERS


def test_factory_ignores_case_and_spaces():
    provider = get_search_provider(Settings(_env_file=None, search_providers="  Mock "))
    assert provider.name == "mock"


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown search provider 'bing'"):
        get_search_provider(Settings(_env_file=None, search_providers="bing"))


def test_factory_rejects_an_empty_list():
    with pytest.raises(ValueError, match="empty"):
        get_search_provider(Settings(_env_file=None, search_providers=" , "))


def test_mock_cannot_be_mixed_with_real_providers(monkeypatch):
    """Fake results must never appear in live research."""
    monkeypatch.setattr("app.core.tools.factory.SUPPORTED_SEARCH_PROVIDERS", ["mock", "serpapi"])
    with pytest.raises(ValueError, match="can't be combined"):
        parse_search_providers(Settings(_env_file=None, search_providers="serpapi,mock"))


def test_a_provider_cannot_be_listed_twice():
    with pytest.raises(ValueError, match="twice"):
        parse_search_providers(Settings(_env_file=None, search_providers="mock,mock"))


def test_provider_label_for_the_research_run():
    assert search_provider_label(Settings(_env_file=None, search_providers=" MOCK ")) == "mock"


def test_search_providers_can_be_set_from_environment(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDERS", "mock")
    monkeypatch.setenv("MOCK_SEARCH_DELAY_MS", "0")
    settings = Settings()
    assert settings.search_providers == "mock"
    assert settings.mock_search_delay_ms == 0
