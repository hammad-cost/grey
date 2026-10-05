"""
Builds the LLM gateway from settings (.env).

This is the only file that knows which provider adapters exist.
Adding a vendor later = write its adapter in providers/, then register it here.

    LLM_MODE=fake → only FakeLLMProvider; every profile uses it.
    LLM_MODE=live → real providers that have a key (Release 0.3: Groq).
"""
from app.core.config.settings import Settings
from app.core.llm.gateway import GatewayPolicy, LLMGateway
from app.core.llm.health import ProviderHealth
from app.core.llm.profiles import build_profiles
from app.core.llm.providers.base import LLMProvider
from app.core.llm.providers.fake import FakeLLMProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.core.llm.router import LLMRouter

# Providers Grey has an adapter for. Routes naming anything else are a configuration error.
KNOWN_PROVIDERS = {"fake", "groq"}


def build_providers(settings: Settings) -> dict[str, LLMProvider]:
    """The providers that can be used right now (a provider without a key is left out)."""
    mode = settings.llm_mode.strip().lower()
    if mode == "fake":
        return {"fake": FakeLLMProvider()}

    providers: dict[str, LLMProvider] = {}
    groq_key = settings.groq_api_key.get_secret_value().strip()
    if groq_key:
        providers["groq"] = OpenAICompatibleProvider("groq", settings.groq_base_url, groq_key)
    return providers


def build_llm_gateway(settings: Settings) -> LLMGateway:
    """
    Build the gateway: profiles from settings, providers that have keys, and the limits.

    Raises:
        ValueError: LLM_MODE is not fake/live, a profile override is malformed,
                    or a route names a provider Grey has no adapter for.
    """
    mode = settings.llm_mode.strip().lower()
    overrides = {
        "fast_cheap": settings.llm_profile_fast_cheap,
        "structured_reasoning": settings.llm_profile_structured_reasoning,
        "high_quality_reasoning": settings.llm_profile_high_quality_reasoning,
        "writing": settings.llm_profile_writing,
        "long_context": settings.llm_profile_long_context,
    }
    profiles = build_profiles(mode, overrides)

    for profile in profiles.values():
        for route in profile.routes:
            if route.provider not in KNOWN_PROVIDERS:
                raise ValueError(
                    f"Profile '{profile.name}' uses provider '{route.provider}', "
                    f"which Grey has no adapter for yet. Known: {sorted(KNOWN_PROVIDERS)}"
                )

    policy = GatewayPolicy(
        attempt_timeout_seconds=settings.llm_timeout_seconds,
        total_deadline_seconds=settings.llm_total_deadline_seconds,
        max_retries=settings.llm_max_retries,
        cooldown_seconds=settings.llm_cooldown_seconds,
        quota_cooldown_seconds=settings.llm_quota_cooldown_seconds,
    )
    router = LLMRouter(profiles, build_providers(settings), ProviderHealth())
    return LLMGateway(router, policy)
