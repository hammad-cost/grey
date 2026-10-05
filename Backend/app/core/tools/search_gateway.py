"""
SearchGateway — several search providers behind one SearchProvider.

Skills keep calling `search(query)` exactly as before; the gateway decides
which real service answers it:

  1. try the providers in the configured order (e.g. SerpAPI, then Tavily),
  2. retry short-lived failures (rate limit, timeout, server error) with a
     growing pause, honouring the provider's retry-after,
  3. fall back to the next provider when one can't answer,
  4. remember which providers are resting, so they aren't asked again too soon:
       rate limit / repeated errors → short cooldown
       searches or credits used up  → long cooldown
       invalid API key              → unusable until the server restarts
  5. if a provider finds nothing, ask the next one too (better coverage).

Every result is stamped with the provider that found it, so evidence always
says where it came from. The gateway never falls back to fake (mock) results.
"""
import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.tools.search import (
    SearchAuthError,
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

logger = logging.getLogger("grey.search")

MAX_RETRY_PAUSE_SECONDS = 30.0
FAILURES_BEFORE_COOLDOWN = 3


@dataclass(frozen=True)
class SearchPolicy:
    """Limits for each search. Built from settings in factory.py."""

    timeout_seconds: float = 20.0          # one attempt at one provider
    max_retries: int = 2                   # extra tries per provider for short-lived failures
    retry_base_seconds: float = 1.0        # first pause; doubles each retry
    cooldown_seconds: float = 60.0         # after rate limits / repeated errors
    quota_cooldown_seconds: float = 3600.0  # after searches/credits run out


class SearchHealth:
    """Remembers which providers are unusable or resting. In memory; resets on restart."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._unavailable: dict[str, str] = {}
        self._cooldown_until: dict[str, float] = {}
        self._failures: dict[str, int] = {}

    def is_usable(self, provider: str) -> bool:
        return provider not in self._unavailable and self._clock() >= self._cooldown_until.get(provider, 0.0)

    def mark_unavailable(self, provider: str, reason: str) -> None:
        self._unavailable[provider] = reason

    def cool_down(self, provider: str, seconds: float) -> None:
        until = self._clock() + seconds
        self._cooldown_until[provider] = max(until, self._cooldown_until.get(provider, 0.0))

    def record_failure(self, provider: str, cooldown_seconds: float) -> None:
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= FAILURES_BEFORE_COOLDOWN:
            self.cool_down(provider, cooldown_seconds)
            self._failures[provider] = 0

    def record_success(self, provider: str) -> None:
        self._failures.pop(provider, None)


class SearchGateway(SearchProvider):
    """Implements SearchProvider by trying real providers in order."""

    name = "search_gateway"

    def __init__(
        self,
        providers: list[SearchProvider],
        policy: SearchPolicy | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = lambda: random.uniform(0.0, 0.5),
    ) -> None:
        self.providers = providers
        self.policy = policy or SearchPolicy()
        self.health = SearchHealth(clock)
        self._sleep = sleep            # tests pass fakes for sleep, clock and jitter
        self._clock = clock
        self._jitter = jitter

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self.providers]

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """
        Run the search on the first provider that can answer it.

        Returns [] only if every usable provider answered with no results.

        Raises:
            SearchUnavailable: no provider could complete the search.
        """
        causes: list[str] = []
        answered = False

        for provider in self.providers:
            if not self.health.is_usable(provider.name):
                continue
            results = await self._try_provider(provider, query, causes)
            if results is None:
                continue                      # failed — try the next provider
            answered = True
            if results:
                return results
            # Answered with nothing: let the next provider have a go.

        if answered:
            return []
        raise SearchUnavailable(
            "No search provider could complete the search"
            + (f" (tried: {', '.join(causes)})." if causes else " (none configured or all resting)."),
            causes=causes,
        )

    async def _try_provider(
        self, provider: SearchProvider, query: SearchQuery, causes: list[str]
    ) -> list[SearchResult] | None:
        """One provider, with retries. Returns its results, or None if it couldn't answer."""
        retries = 0
        while True:
            began = self._clock()
            try:
                results = await asyncio.wait_for(provider.search(query), self.policy.timeout_seconds)
            except asyncio.TimeoutError:
                error: SearchProviderError = SearchTimeout("The search provider did not answer in time.")
            except SearchProviderError as caught:
                error = caught
            else:
                self.health.record_success(provider.name)
                self._log(provider, query, "ok", began, len(results))
                return [r if r.provider else r.model_copy(update={"provider": provider.name}) for r in results]

            self._log(provider, query, error.kind, began)
            causes.append(error.kind)

            if isinstance(error, SearchAuthError):
                self.health.mark_unavailable(provider.name, error.kind)
                return None
            if isinstance(error, SearchQuotaExhausted):
                self.health.cool_down(provider.name, self.policy.quota_cooldown_seconds)
                return None

            if error.retryable and retries < self.policy.max_retries:
                retries += 1
                await self._sleep(self._pause(retries - 1, getattr(error, "retry_after", None)))
                continue

            if isinstance(error, SearchRateLimited):
                self.health.cool_down(provider.name, max(self.policy.cooldown_seconds, error.retry_after or 0.0))
            elif isinstance(error, (SearchServerError, SearchTimeout)):
                self.health.record_failure(provider.name, self.policy.cooldown_seconds)
            return None

    def _pause(self, retries: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, MAX_RETRY_PAUSE_SECONDS)
        return min(self.policy.retry_base_seconds * (2 ** retries) + self._jitter(), MAX_RETRY_PAUSE_SECONDS)

    def _log(self, provider: SearchProvider, query: SearchQuery, outcome: str, began: float, results: int = 0) -> None:
        """One line per attempt. The query text is not logged (it can contain the student's topic)."""
        logger.info(
            "search_call provider=%s focus=%s outcome=%s results=%d latency_ms=%d",
            provider.name, query.focus.value, outcome, results, int((self._clock() - began) * 1000),
        )
