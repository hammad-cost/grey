"""
Tests for SearchGateway: ordered fallback, retries, cooldowns (Release 0.4, Step 1).

Only scripted fake providers are used — no network, no keys, no cost.
Time is faked: `sleep` moves a fake clock instead of waiting.
"""
import asyncio
import logging

import pytest

from app.core.tools.search import (
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
from app.core.tools.search_gateway import SearchGateway, SearchPolicy

QUERY = SearchQuery(text='"Navy" startups', focus=SearchFocus.COMPANIES)


def result(n: int) -> SearchResult:
    return SearchResult(title=f"Result {n}", url=f"https://site-{n}.com/page", snippet="Some text.")


class ScriptedProvider(SearchProvider):
    """Answers from a queue: a list of results, an exception to raise, or 'hang' (never answers)."""

    def __init__(self, name: str, replies: list) -> None:
        self.name = name
        self.replies = list(replies)
        self.calls = 0

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.calls += 1
        reply = self.replies.pop(0)
        if reply == "hang":
            await asyncio.sleep(3600)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def time_():
    return FakeTime()


def gateway(providers, time_, **policy) -> SearchGateway:
    defaults = dict(timeout_seconds=5.0, max_retries=2, retry_base_seconds=1.0,
                    cooldown_seconds=60.0, quota_cooldown_seconds=3600.0)
    defaults.update(policy)
    return SearchGateway(providers, SearchPolicy(**defaults), sleep=time_.sleep, clock=time_.clock, jitter=lambda: 0.0)


# ── Success ───────────────────────────────────────────────────────────────────

async def test_first_provider_answers_and_results_are_stamped(time_):
    serp = ScriptedProvider("serpapi", [[result(1), result(2)]])
    tavily = ScriptedProvider("tavily", [])

    results = await gateway([serp, tavily], time_).search(QUERY)

    assert [r.title for r in results] == ["Result 1", "Result 2"]
    assert {r.provider for r in results} == {"serpapi"}
    assert tavily.calls == 0


async def test_a_providers_own_stamp_is_kept(time_):
    stamped = result(1).model_copy(update={"provider": "serpapi-scholar"})
    results = await gateway([ScriptedProvider("serpapi", [[stamped]])], time_).search(QUERY)
    assert results[0].provider == "serpapi-scholar"


async def test_empty_answer_asks_the_next_provider(time_):
    serp = ScriptedProvider("serpapi", [[]])
    tavily = ScriptedProvider("tavily", [[result(3)]])

    results = await gateway([serp, tavily], time_).search(QUERY)

    assert [r.provider for r in results] == ["tavily"]


async def test_everyone_empty_returns_no_results_not_an_error(time_):
    results = await gateway([ScriptedProvider("serpapi", [[]]), ScriptedProvider("tavily", [[]])], time_).search(QUERY)
    assert results == []


# ── Short-lived failures: retry, then fall back ───────────────────────────────

async def test_rate_limit_waits_as_asked_then_succeeds(time_):
    serp = ScriptedProvider("serpapi", [SearchRateLimited("busy", retry_after=7), [result(1)]])
    results = await gateway([serp], time_).search(QUERY)

    assert results[0].provider == "serpapi"
    assert time_.sleeps == [7]


async def test_server_errors_retry_with_growing_pauses(time_):
    serp = ScriptedProvider("serpapi", [SearchServerError("500"), SearchServerError("503"), [result(1)]])
    await gateway([serp], time_).search(QUERY)
    assert time_.sleeps == [1.0, 2.0]


async def test_rate_limit_after_retries_falls_back_and_rests_the_provider(time_):
    serp = ScriptedProvider("serpapi", [SearchRateLimited("busy")] * 3)
    tavily = ScriptedProvider("tavily", [[result(1)], [result(2)]])
    gw = gateway([serp, tavily], time_)

    first = await gw.search(QUERY)
    assert first[0].provider == "tavily"
    assert serp.calls == 3

    # The next search skips the resting provider.
    second = await gw.search(QUERY)
    assert second[0].provider == "tavily"
    assert serp.calls == 3


async def test_rested_provider_is_used_again_later(time_):
    serp = ScriptedProvider("serpapi", [SearchRateLimited("busy")] * 3 + [[result(9)]])
    tavily = ScriptedProvider("tavily", [[result(1)]])
    gw = gateway([serp, tavily], time_)
    await gw.search(QUERY)

    time_.now += 61
    assert (await gw.search(QUERY))[0].provider == "serpapi"


async def test_slow_provider_times_out_then_falls_back():
    """Uses real time: the slow provider never answers within the 0.05 s timeout."""
    slow = ScriptedProvider("serpapi", ["hang"])
    tavily = ScriptedProvider("tavily", [[result(1)]])
    gw = SearchGateway([slow, tavily], SearchPolicy(timeout_seconds=0.05, max_retries=0))

    results = await gw.search(QUERY)
    assert results[0].provider == "tavily"


async def test_repeated_server_errors_rest_the_provider(time_):
    serp = ScriptedProvider("serpapi", [SearchServerError("500")] * 9)
    tavily = ScriptedProvider("tavily", [[result(1)]] * 3)
    gw = gateway([serp, tavily], time_)
    for _ in range(3):
        await gw.search(QUERY)
    assert gw.health.is_usable("serpapi") is False


# ── Failures that skip retrying ───────────────────────────────────────────────

async def test_out_of_credits_falls_back_at_once_and_rests_long(time_):
    serp = ScriptedProvider("serpapi", [SearchQuotaExhausted("Your account has run out of searches.")])
    tavily = ScriptedProvider("tavily", [[result(1)]])
    gw = gateway([serp, tavily], time_)

    results = await gw.search(QUERY)
    assert results[0].provider == "tavily"
    assert time_.sleeps == []

    time_.now += 120                       # past a normal cooldown, not the quota one
    assert gw.health.is_usable("serpapi") is False


async def test_invalid_key_makes_the_provider_unusable(time_):
    serp = ScriptedProvider("serpapi", [SearchAuthError("401")])
    tavily = ScriptedProvider("tavily", [[result(1)]])
    gw = gateway([serp, tavily], time_)

    await gw.search(QUERY)
    time_.now += 10_000
    assert gw.health.is_usable("serpapi") is False


async def test_bad_request_falls_back_without_retrying(time_):
    serp = ScriptedProvider("serpapi", [SearchBadRequest("unsupported filter")])
    tavily = ScriptedProvider("tavily", [[result(1)]])
    results = await gateway([serp, tavily], time_).search(QUERY)
    assert results[0].provider == "tavily"
    assert serp.calls == 1


async def test_unknown_provider_error_falls_back_without_retrying(time_):
    serp = ScriptedProvider("serpapi", [SearchProviderError("odd failure")])
    tavily = ScriptedProvider("tavily", [[result(1)]])
    results = await gateway([serp, tavily], time_).search(QUERY)
    assert results[0].provider == "tavily"
    assert serp.calls == 1


# ── Nothing works ─────────────────────────────────────────────────────────────

async def test_all_providers_failing_raises_unavailable_with_causes(time_):
    serp = ScriptedProvider("serpapi", [SearchQuotaExhausted("out")])
    tavily = ScriptedProvider("tavily", [SearchAuthError("401")])

    with pytest.raises(SearchUnavailable) as caught:
        await gateway([serp, tavily], time_).search(QUERY)
    assert caught.value.causes == ["quota_exhausted", "auth_error"]


async def test_unavailable_is_a_search_provider_error(time_):
    """The research skill already turns SearchProviderError into a safe research_failed event."""
    with pytest.raises(SearchProviderError):
        await gateway([], time_).search(QUERY)


async def test_no_providers_configured_raises_unavailable(time_):
    with pytest.raises(SearchUnavailable, match="none configured"):
        await gateway([], time_).search(QUERY)


# ── Site-limited searches (Release 0.4.1) ─────────────────────────────────────

class SiteKeepingProvider(ScriptedProvider):
    """Like Tavily: returns only the requested sites, so it should be asked first."""

    def keeps_to_sites(self, query: SearchQuery) -> bool:
        return True


SITE_QUERY = SearchQuery(text='"Navy" startups', include_domains=["ycombinator.com"])


async def test_site_limited_search_asks_the_site_keeping_provider_first(time_):
    serp = ScriptedProvider("serpapi", [[result(1)]])
    tav = SiteKeepingProvider("tavily", [[result(2)]])

    results = await gateway([serp, tav], time_).search(SITE_QUERY)

    assert [r.title for r in results] == ["Result 2"]
    assert (serp.calls, tav.calls) == (0, 1)


async def test_site_limited_search_still_falls_back_to_the_other_provider(time_):
    serp = ScriptedProvider("serpapi", [[result(1)]])
    tav = SiteKeepingProvider("tavily", [[]])

    results = await gateway([serp, tav], time_).search(SITE_QUERY)

    assert [r.title for r in results] == ["Result 1"]
    assert (serp.calls, tav.calls) == (1, 1)


async def test_unlimited_search_keeps_the_configured_order(time_):
    serp = ScriptedProvider("serpapi", [[result(1)]])
    tav = SiteKeepingProvider("tavily", [[result(2)]])

    results = await gateway([serp, tav], time_).search(QUERY)

    assert [r.title for r in results] == ["Result 1"]
    assert tav.calls == 0


# ── Logging ───────────────────────────────────────────────────────────────────

async def test_logs_each_attempt_without_the_query_text(time_, caplog):
    serp = ScriptedProvider("serpapi", [SearchTimeout("slow"), [result(1)]])
    with caplog.at_level(logging.INFO, logger="grey.search"):
        await gateway([serp], time_).search(QUERY)

    lines = [r.getMessage() for r in caplog.records if r.name == "grey.search"]
    assert len(lines) == 2
    assert "provider=serpapi focus=companies outcome=timeout" in lines[0]
    assert "outcome=ok results=1" in lines[1]
    assert all("Navy" not in line for line in lines)
