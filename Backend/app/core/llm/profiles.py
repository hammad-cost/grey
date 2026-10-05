"""
Model profiles — the only way skills choose a model.

A skill says WHAT kind of work it needs (e.g. structured_reasoning).
This file says WHICH provider/model routes serve that work, in order.
Any profile can be overridden from .env without touching code, e.g.:

    LLM_PROFILE_STRUCTURED_REASONING=groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b

Release 0.3 has one real provider (Groq), so every default route is a Groq model.
Model facts below come from Groq's model docs (checked 2026-10-05).
"""
from app.core.llm.schemas import ModelProfile, ModelRoute

# ── Profile names (skills use these constants) ────────────────────────────────

FAST_CHEAP = "fast_cheap"
STRUCTURED_REASONING = "structured_reasoning"
HIGH_QUALITY_REASONING = "high_quality_reasoning"
WRITING = "writing"
LONG_CONTEXT = "long_context"

PROFILE_NAMES = [FAST_CHEAP, STRUCTURED_REASONING, HIGH_QUALITY_REASONING, WRITING, LONG_CONTEXT]

# ── Default routes for LLM_MODE=live, as "provider:model" ─────────────────────

DEFAULT_PROFILE_ROUTES: dict[str, list[str]] = {
    FAST_CHEAP: ["groq:openai/gpt-oss-20b"],
    STRUCTURED_REASONING: ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"],
    HIGH_QUALITY_REASONING: ["groq:openai/gpt-oss-120b"],
    WRITING: ["groq:openai/gpt-oss-120b"],
    LONG_CONTEXT: ["groq:openai/gpt-oss-120b"],
}

# ── What we know about each model ─────────────────────────────────────────────
# (context window, most output tokens we ask for, provider can enforce the JSON schema)

MODEL_CATALOG: dict[str, tuple[int, int, bool]] = {
    "groq:openai/gpt-oss-120b": (131_072, 8_192, True),
    "groq:openai/gpt-oss-20b": (131_072, 8_192, True),
    "groq:llama-3.3-70b-versatile": (131_072, 8_192, False),
    "groq:llama-3.1-8b-instant": (131_072, 8_192, False),
    "fake:fake-model": (1_000_000, 8_192, True),
}

# Used for a model that isn't in the catalog (e.g. a new one set in .env):
# assume a small context and no schema enforcement, to be safe.
UNKNOWN_MODEL_DEFAULTS = (32_768, 4_096, False)

# In LLM_MODE=fake, every profile uses this one route.
FAKE_ROUTE = "fake:fake-model"


def parse_route(text: str) -> ModelRoute:
    """Turn "groq:openai/gpt-oss-120b" into a ModelRoute."""
    provider, separator, model = text.strip().partition(":")
    if not separator or not provider or not model:
        raise ValueError(f"Invalid LLM route '{text}'. Expected 'provider:model'.")
    context_window, max_output, strict = MODEL_CATALOG.get(f"{provider}:{model}", UNKNOWN_MODEL_DEFAULTS)
    return ModelRoute(
        provider=provider,
        model=model,
        context_window=context_window,
        max_output_tokens=max_output,
        strict_schema=strict,
    )


def parse_routes(text: str) -> tuple[ModelRoute, ...]:
    """Turn a comma-separated list of routes into ModelRoutes (order kept)."""
    routes = tuple(parse_route(part) for part in text.split(",") if part.strip())
    if not routes:
        raise ValueError("An LLM profile needs at least one route.")
    return routes


def build_profiles(mode: str, overrides: dict[str, str]) -> dict[str, ModelProfile]:
    """
    Build every profile for the given mode.

    Args:
        mode:      "fake" (every profile uses the fake model) or "live".
        overrides: profile name → "provider:model,…" from .env (empty = use default).
    """
    if mode not in ("fake", "live"):
        raise ValueError(f"LLM_MODE must be 'fake' or 'live', not '{mode}'.")

    profiles = {}
    for name in PROFILE_NAMES:
        if mode == "fake":
            routes = parse_routes(FAKE_ROUTE)
        else:
            routes = parse_routes(overrides.get(name) or ",".join(DEFAULT_PROFILE_ROUTES[name]))
        profiles[name] = ModelProfile(name=name, routes=routes)
    return profiles
