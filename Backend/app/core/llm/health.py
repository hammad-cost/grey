"""
ProviderHealth — remembers which providers and models are currently unusable.

Two levels:
  provider level — e.g. "groq": an invalid API key makes every Groq model unusable.
  route level    — e.g. "groq:openai/gpt-oss-120b": rate limits and daily quotas
                   are per model, so one model can cool down while another works.

Kept in memory, so it resets when the server restarts. That is enough for one
server process; sharing it between processes (e.g. Redis) is deferred.
"""
import time
from collections.abc import Callable

from app.core.llm.schemas import ModelRoute

# After this many server errors/timeouts in a row, a route cools down.
FAILURES_BEFORE_COOLDOWN = 3


class ProviderHealth:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock                       # tests pass a fake clock
        self._unavailable: dict[str, str] = {}    # provider → reason (until restart)
        self._cooldown_until: dict[str, float] = {}   # route key → time it may be used again
        self._failures: dict[str, int] = {}       # route key → consecutive transient failures

    def is_usable(self, route: ModelRoute) -> bool:
        if route.provider in self._unavailable:
            return False
        return self._clock() >= self._cooldown_until.get(route.key, 0.0)

    def mark_unavailable(self, provider: str, reason: str) -> None:
        """The provider can't be used at all until the server restarts (e.g. invalid key)."""
        self._unavailable[provider] = reason

    def cool_down(self, route: ModelRoute, seconds: float) -> None:
        """Skip this route for `seconds` (never shortens an existing, longer cooldown)."""
        until = self._clock() + seconds
        self._cooldown_until[route.key] = max(until, self._cooldown_until.get(route.key, 0.0))

    def record_failure(self, route: ModelRoute, cooldown_seconds: float) -> None:
        """Count a transient failure; after several in a row, cool the route down."""
        self._failures[route.key] = self._failures.get(route.key, 0) + 1
        if self._failures[route.key] >= FAILURES_BEFORE_COOLDOWN:
            self.cool_down(route, cooldown_seconds)
            self._failures[route.key] = 0

    def record_success(self, route: ModelRoute) -> None:
        self._failures.pop(route.key, None)
