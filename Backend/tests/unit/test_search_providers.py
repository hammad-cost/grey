"""
Tests for the real search adapters (Release 0.4, Step 2): SerpAPI and Tavily.

Every HTTP call goes to a fake transport — nothing leaves the test, no key
is used, no credits are spent. Checks the request each adapter sends, how
it reads the response, and that every vendor error becomes the right Grey error.
"""
import json
from datetime import date, timedelta

import httpx
import pytest

from app.core.config.settings import Settings
from app.core.tools import get_search_provider
from app.core.tools.providers.common import make_result, parse_date, recency_bucket
from app.core.tools.providers.serpapi import SerpApiProvider
from app.core.tools.providers.tavily import TavilySearchProvider
from app.core.tools.search import (
    SearchAuthError,
    SearchBadRequest,
    SearchFocus,
    SearchQuery,
    SearchQuotaExhausted,
    SearchRateLimited,
    SearchServerError,
    SearchTimeout,
)
from app.core.tools.search_gateway import SearchGateway

SERP_KEY = "serp_test_secret"
TAVILY_KEY = "tvly-test-secret"


def fake_client(handler) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(record)), seen


def serp(handler) -> tuple[SerpApiProvider, list[httpx.Request]]:
    client, seen = fake_client(handler)
    return SerpApiProvider(SERP_KEY, url="https://serpapi.example/search", http_client=client), seen


def tavily(handler) -> tuple[TavilySearchProvider, list[httpx.Request]]:
    client, seen = fake_client(handler)
    return TavilySearchProvider(TAVILY_KEY, url="https://tavily.example/search", http_client=client), seen


def ok(body: dict) -> callable:
    return lambda request: httpx.Response(200, json=body)


ORGANIC = {"organic_results": [
    {"position": 1, "title": "Harbor AI — vessel monitoring", "link": "https://harbor-ai.com/",
     "snippet": "Harbor AI detects unusual ship movements in real time.", "source": "Harbor AI",
     "date": "Mar 3, 2026"},
    {"position": 2, "title": "No link here", "snippet": "Missing link is skipped."},
    {"position": 3, "title": "No snippet", "link": "https://x.com/"},
    {"position": 4, "title": "Navy programme", "link": "https://www.navy.mil/programme",
     "snippet": "  The   programme funds   maritime   autonomy. ", "displayed_link": "www.navy.mil › programme"},
]}


# ── Shared helpers ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("2026-03-01", date(2026, 3, 1)),
    ("2026-03-01T10:00:00Z", date(2026, 3, 1)),
    ("Mar 1, 2026", date(2026, 3, 1)),
    ("1 March 2026", date(2026, 3, 1)),
    ("not a date", None),
    ("", None),
    (None, None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_parse_relative_dates():
    today = date(2026, 10, 6)
    assert parse_date("3 days ago", today) == today - timedelta(days=3)
    assert parse_date("2 weeks ago", today) == today - timedelta(days=14)
    assert parse_date("5 hours ago", today) == today


def test_make_result_skips_unusable_items():
    assert make_result(title="t", url="ftp://x.com", snippet="s", provider="p") is None
    assert make_result(title="", url="https://x.com", snippet="s", provider="p") is None
    assert make_result(title="t", url=None, snippet="s", provider="p") is None
    result = make_result(title=" t ", url="https://x.com ", snippet="a\n  b", provider="p")
    assert (result.title, result.url, result.snippet, result.provider) == ("t", "https://x.com", "a b", "p")


@pytest.mark.parametrize("days, bucket", [(None, None), (1, "day"), (5, "week"), (30, "month"), (400, "year")])
def test_recency_bucket(days, bucket):
    assert recency_bucket(days) == bucket


# ── SerpAPI: requests ─────────────────────────────────────────────────────────

async def test_serpapi_web_search_request_and_results():
    provider, seen = serp(ok(ORGANIC))

    results = await provider.search(SearchQuery(text='"Navy" startups', focus=SearchFocus.COMPANIES, max_results=5))

    params = seen[0].url.params
    assert seen[0].method == "GET"
    assert params["engine"] == "google"
    assert params["q"] == '"Navy" startups'
    assert params["api_key"] == SERP_KEY
    assert "tbm" not in params
    # Items without a link or snippet are skipped; text is tidied.
    assert [r.url for r in results] == ["https://harbor-ai.com/", "https://www.navy.mil/programme"]
    assert results[0].publisher == "Harbor AI"
    assert results[0].published_date == date(2026, 3, 3)
    assert results[1].snippet == "The programme funds maritime autonomy."
    assert results[1].publisher == "www.navy.mil › programme"
    assert {r.provider for r in results} == {"serpapi"}


async def test_serpapi_site_filters_and_recency():
    provider, seen = serp(ok({"organic_results": []}))
    query = SearchQuery(text="maritime startups", include_domains=["ycombinator.com", "producthunt.com"], recency_days=200)

    await provider.search(query)

    params = seen[0].url.params
    assert params["q"] == "maritime startups (site:ycombinator.com OR site:producthunt.com)"
    assert params["tbs"] == "qdr:y"


async def test_serpapi_news_uses_the_news_tab():
    news = {"news_results": [{"title": "Navy tests AI", "link": "https://news.example.org/a",
                              "snippet": "The navy trialled anomaly detection.",
                              "source": "Defense News", "published_at": "2026-09-30T08:00:00Z"}]}
    provider, seen = serp(ok(news))

    [result] = await provider.search(SearchQuery(text="navy AI", focus=SearchFocus.NEWS))

    assert seen[0].url.params["tbm"] == "nws"
    assert result.publisher == "Defense News"
    assert result.published_date == date(2026, 9, 30)


async def test_serpapi_research_uses_google_scholar():
    scholar = {"organic_results": [{"title": "Vessel anomaly detection with AIS",
                                    "link": "https://ieeexplore.ieee.org/document/1",
                                    "snippet": "We propose a trajectory model.",
                                    "publication_info": {"summary": "J Smith - IEEE Access, 2024 - ieeexplore.ieee.org"}}]}
    provider, seen = serp(ok(scholar))

    [result] = await provider.search(SearchQuery(text="AIS anomaly", focus=SearchFocus.RESEARCH, recency_days=730))

    params = seen[0].url.params
    assert params["engine"] == "google_scholar"
    assert params["as_ylo"] == str(date.today().year - 2)
    assert result.publisher == "J Smith - IEEE Access, 2024 - ieeexplore.ieee.org"


async def test_serpapi_respects_max_results():
    many = {"organic_results": [{"title": f"R{i}", "link": f"https://r{i}.com/", "snippet": "s"} for i in range(10)]}
    provider, _ = serp(ok(many))
    assert len(await provider.search(SearchQuery(text="x", max_results=3))) == 3


async def test_serpapi_no_results_message_is_not_an_error():
    provider, _ = serp(ok({"error": "Google hasn't returned any results for this query."}))
    assert await provider.search(SearchQuery(text="zzz")) == []


# ── SerpAPI: errors ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("status, message, expected", [
    (401, "Invalid API key.", SearchAuthError),
    (403, "Account lacks permission.", SearchAuthError),
    (429, "Your account has run out of searches.", SearchQuotaExhausted),
    (429, "You have exceeded the hourly throughput limit for your plan.", SearchRateLimited),
    (400, "Missing query `q` parameter.", SearchBadRequest),
    (410, "Search expired.", SearchBadRequest),
    (500, "Internal error.", SearchServerError),
    (503, "Service unavailable.", SearchServerError),
])
async def test_serpapi_http_errors(status, message, expected):
    provider, _ = serp(lambda r: httpx.Response(status, json={"error": message}))
    with pytest.raises(expected) as caught:
        await provider.search(SearchQuery(text="x"))
    assert caught.value.provider == "serpapi"
    assert SERP_KEY not in str(caught.value)


async def test_serpapi_other_error_in_a_200_is_a_server_error():
    provider, _ = serp(ok({"error": "Something went wrong on our side."}))
    with pytest.raises(SearchServerError):
        await provider.search(SearchQuery(text="x"))


async def test_serpapi_timeout_and_connection_errors():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SearchTimeout):
        await serp(slow)[0].search(SearchQuery(text="x"))
    with pytest.raises(SearchServerError) as caught:
        await serp(down)[0].search(SearchQuery(text="x"))
    assert SERP_KEY not in str(caught.value)


# ── Tavily: requests ──────────────────────────────────────────────────────────

TAVILY_BODY = {"results": [
    {"title": "Harbor AI", "url": "https://harbor-ai.com/", "content": "Detects unusual ship movements.",
     "score": 0.9, "published_date": "2026-02-01"},
    {"title": "Broken", "url": "not-a-url", "content": "skipped"},
]}


async def test_tavily_request_and_results():
    provider, seen = tavily(ok(TAVILY_BODY))
    query = SearchQuery(text="maritime startups", include_domains=["ycombinator.com"], recency_days=30, max_results=4)

    results = await provider.search(query)

    request = seen[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {TAVILY_KEY}"
    assert body == {
        "query": "maritime startups", "topic": "general", "search_depth": "basic", "max_results": 4,
        "include_answer": False, "include_raw_content": False,
        "include_domains": ["ycombinator.com"], "time_range": "month",
    }
    assert [r.url for r in results] == ["https://harbor-ai.com/"]
    assert results[0].published_date == date(2026, 2, 1)
    assert results[0].provider == "tavily"


async def test_tavily_news_topic_and_no_optional_fields_by_default():
    provider, seen = tavily(ok({"results": []}))
    await provider.search(SearchQuery(text="navy AI", focus=SearchFocus.NEWS))

    body = json.loads(seen[0].content)
    assert body["topic"] == "news"
    assert "include_domains" not in body and "time_range" not in body


# ── Tavily: errors ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status, expected", [
    (401, SearchAuthError),
    (429, SearchRateLimited),
    (432, SearchQuotaExhausted),
    (433, SearchQuotaExhausted),
    (400, SearchBadRequest),
    (422, SearchBadRequest),
    (500, SearchServerError),
])
async def test_tavily_http_errors(status, expected):
    provider, _ = tavily(lambda r: httpx.Response(status, json={"detail": {"error": "problem"}}))
    with pytest.raises(expected) as caught:
        await provider.search(SearchQuery(text="x"))
    assert caught.value.provider == "tavily"
    assert TAVILY_KEY not in str(caught.value)


async def test_tavily_rate_limit_carries_retry_after():
    provider, _ = tavily(lambda r: httpx.Response(429, json={"detail": "slow down"}, headers={"retry-after": "9"}))
    with pytest.raises(SearchRateLimited) as caught:
        await provider.search(SearchQuery(text="x"))
    assert caught.value.retry_after == 9.0


async def test_tavily_unreadable_response_is_a_server_error():
    provider, _ = tavily(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(SearchServerError):
        await provider.search(SearchQuery(text="x"))


# ── Factory: building the gateway from settings ───────────────────────────────

def test_factory_builds_a_gateway_in_the_configured_order():
    settings = Settings(_env_file=None, search_providers="serpapi,tavily",
                        serpapi_api_key="k1", tavily_api_key="k2")
    gateway = get_search_provider(settings)

    assert isinstance(gateway, SearchGateway)
    assert gateway.provider_names == ["serpapi", "tavily"]


def test_providers_without_a_key_are_skipped():
    gateway = get_search_provider(Settings(_env_file=None, search_providers="serpapi,tavily", tavily_api_key="k2"))
    assert gateway.provider_names == ["tavily"]


def test_order_comes_from_settings():
    gateway = get_search_provider(Settings(_env_file=None, search_providers="tavily,serpapi",
                                           serpapi_api_key="k1", tavily_api_key="k2"))
    assert gateway.provider_names == ["tavily", "serpapi"]


def test_search_keys_are_hidden_when_settings_are_printed():
    settings = Settings(_env_file=None, serpapi_api_key="serp-secret", tavily_api_key="tvly-secret")
    assert "serp-secret" not in repr(settings) and "tvly-secret" not in repr(settings)


async def test_serpapi_scholar_ignores_site_filters():
    """Scholar only searches papers already; site filters would just narrow it."""
    provider, seen = serp(ok({"organic_results": []}))
    await provider.search(SearchQuery(text="AIS anomaly", focus=SearchFocus.RESEARCH,
                                      include_domains=["arxiv.org", "ieeexplore.ieee.org"]))
    assert seen[0].url.params["q"] == "AIS anomaly"


def test_missing_search_keys_are_reported_at_startup(caplog):
    with caplog.at_level("WARNING", logger="grey.search"):
        gateway = get_search_provider(Settings(_env_file=None, search_providers="serpapi,tavily"))
    assert gateway.provider_names == []
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "serpapi, tavily" in message and "research will fail" in message


def test_no_warning_when_all_keys_are_set(caplog):
    with caplog.at_level("WARNING", logger="grey.search"):
        get_search_provider(Settings(_env_file=None, search_providers="serpapi", serpapi_api_key="k"))
    assert not [r for r in caplog.records if r.name == "grey.search"]
