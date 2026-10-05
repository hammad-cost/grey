"""
LLMRouter — decides which routes the gateway may try for a request, in order.

A route is skipped when:
  - its provider isn't set up (e.g. no API key in .env),
  - its provider or model is unavailable / cooling down (see health.py),
  - the request clearly won't fit in its context window.
"""
from app.core.llm.health import ProviderHealth
from app.core.llm.providers.base import LLMProvider
from app.core.llm.schemas import ModelProfile, ModelRoute


class LLMRouter:
    def __init__(
        self,
        profiles: dict[str, ModelProfile],
        providers: dict[str, LLMProvider],
        health: ProviderHealth,
    ) -> None:
        self._profiles = profiles
        self._providers = providers
        self.health = health

    def provider(self, name: str) -> LLMProvider:
        return self._providers[name]

    def has_provider(self, name: str) -> bool:
        return name in self._providers

    def profile(self, name: str) -> ModelProfile:
        """Raises ValueError for an unknown profile — that is a bug in the calling skill."""
        if name not in self._profiles:
            raise ValueError(f"Unknown LLM profile '{name}'. Known: {sorted(self._profiles)}")
        return self._profiles[name]

    def usable_routes(self, profile_name: str, needed_tokens: int) -> list[ModelRoute]:
        """
        The profile's routes that can be tried right now, in preference order.

        needed_tokens = estimated input tokens + output tokens requested.
        """
        return [
            route
            for route in self.profile(profile_name).routes
            if route.provider in self._providers
            and self.health.is_usable(route)
            and needed_tokens <= route.context_window
        ]
