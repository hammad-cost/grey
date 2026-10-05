"""
Tests for building the LLM gateway from settings: modes, profiles, overrides, keys.
"""
import pytest
from pydantic import BaseModel

from app.core.config.settings import Settings
from app.core.llm import PROFILE_NAMES, STRUCTURED_REASONING, LLMRequest, LLMUnavailable, build_llm_gateway
from app.core.llm.profiles import parse_route
from app.core.llm.providers.fake import FakeLLMProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider


def make_settings(**values) -> Settings:
    """Settings that ignore the real .env file, so tests don't depend on it."""
    return Settings(_env_file=None, **values)


class Answer(BaseModel):
    a: str


def test_the_five_profiles_exist():
    assert PROFILE_NAMES == [
        "fast_cheap", "structured_reasoning", "high_quality_reasoning", "writing", "long_context",
    ]


def test_fake_mode_is_the_default():
    assert make_settings().llm_mode == "fake"


def test_fake_mode_routes_every_profile_to_the_fake_provider():
    gateway = build_llm_gateway(make_settings())
    for name in PROFILE_NAMES:
        [route] = gateway.router.profile(name).routes
        assert route.key == "fake:fake-model"
    assert isinstance(gateway.router.provider("fake"), FakeLLMProvider)


async def test_fake_mode_answers_through_a_responder():
    gateway = build_llm_gateway(make_settings())
    gateway.router.provider("fake").add_responder("Answer", lambda data: {"a": "fake"})

    result = await gateway.generate_structured(
        LLMRequest(skill="t", profile=STRUCTURED_REASONING, instructions="i", input={}, output_schema=Answer)
    )
    assert result.output.a == "fake"
    assert result.provider == "fake"


def test_live_mode_structured_reasoning_uses_groq_120b_then_20b():
    gateway = build_llm_gateway(make_settings(llm_mode="live", groq_api_key="gsk_x"))
    routes = gateway.router.profile(STRUCTURED_REASONING).routes

    assert [r.key for r in routes] == ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"]
    assert all(r.strict_schema and r.context_window == 131_072 for r in routes)
    assert isinstance(gateway.router.provider("groq"), OpenAICompatibleProvider)


async def test_live_mode_without_a_key_has_no_usable_model():
    gateway = build_llm_gateway(make_settings(llm_mode="live", groq_api_key=""))
    with pytest.raises(LLMUnavailable, match="no usable model"):
        await gateway.generate_structured(
            LLMRequest(skill="t", profile=STRUCTURED_REASONING, instructions="i", input={}, output_schema=Answer)
        )


def test_profile_can_be_overridden_from_settings():
    gateway = build_llm_gateway(make_settings(
        llm_mode="live", groq_api_key="gsk_x",
        llm_profile_structured_reasoning="groq:llama-3.3-70b-versatile , groq:openai/gpt-oss-20b",
    ))
    routes = gateway.router.profile(STRUCTURED_REASONING).routes
    assert [r.key for r in routes] == ["groq:llama-3.3-70b-versatile", "groq:openai/gpt-oss-20b"]
    assert routes[0].strict_schema is False      # Groq can't enforce schemas on this model


def test_unknown_model_gets_safe_defaults():
    route = parse_route("groq:some-new-model")
    assert route.strict_schema is False
    assert route.context_window == 32_768


@pytest.mark.parametrize("bad", ["groq", ":model", "groq:", ""])
def test_malformed_route_is_rejected(bad):
    with pytest.raises(ValueError):
        build_llm_gateway(make_settings(llm_mode="live", llm_profile_writing=bad or ","))


def test_provider_without_an_adapter_is_rejected():
    with pytest.raises(ValueError, match="no adapter"):
        build_llm_gateway(make_settings(llm_mode="live", llm_profile_writing="openai:gpt-x"))


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="LLM_MODE"):
        build_llm_gateway(make_settings(llm_mode="sometimes"))


def test_limits_come_from_settings():
    gateway = build_llm_gateway(make_settings(
        llm_timeout_seconds=10, llm_total_deadline_seconds=40, llm_max_retries=1,
        llm_cooldown_seconds=5, llm_quota_cooldown_seconds=50,
    ))
    policy = gateway.policy
    assert (policy.attempt_timeout_seconds, policy.total_deadline_seconds, policy.max_retries,
            policy.cooldown_seconds, policy.quota_cooldown_seconds) == (10, 40, 1, 5, 50)


def test_api_key_is_hidden_when_settings_are_printed():
    settings = make_settings(groq_api_key="gsk_super_secret")
    assert "gsk_super_secret" not in repr(settings)
