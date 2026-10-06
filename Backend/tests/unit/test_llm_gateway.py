"""
Tests for the LLM gateway: routing, retries, fallback, cooldowns, validation.

Only FakeLLMProvider is used — no network, no keys, no cost.
Time is faked too: `sleep` advances a fake clock instead of waiting.
"""
import logging

import pytest
from pydantic import BaseModel, Field

from app.core.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMContextTooLong,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMRefusal,
    LLMServerError,
    LLMTimeout,
    LLMUnavailable,
)
from app.core.llm.gateway import GatewayPolicy, LLMGateway
from app.core.llm.health import ProviderHealth
from app.core.llm.providers.fake import FakeLLMProvider
from app.core.llm.router import LLMRouter
from app.core.llm.schema_tools import strict_json_schema
from app.core.llm.schemas import LLMRequest, ModelProfile, ModelRoute

PROFILE = "structured_reasoning"
SECRET_INPUT = "TOP-SECRET-EVIDENCE-TEXT"


class Answer(BaseModel):
    """A tiny output schema for the tests."""
    title: str = Field(min_length=1)
    score: int


GOOD = {"title": "Vessel anomalies", "score": 3}


def route(provider: str, model: str, context: int = 100_000) -> ModelRoute:
    return ModelRoute(provider=provider, model=model, context_window=context,
                      max_output_tokens=1_000, strict_schema=True)


A = route("p1", "model-a")
B = route("p1", "model-b")
C = route("p2", "model-c")


class FakeTime:
    """A clock that only moves when the gateway 'sleeps' (or a test moves it)."""
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


@pytest.fixture
def providers():
    return {"p1": FakeLLMProvider("p1"), "p2": FakeLLMProvider("p2")}


def make_gateway(providers, time_, routes=(A, B, C), **policy) -> LLMGateway:
    profiles = {PROFILE: ModelProfile(name=PROFILE, routes=tuple(routes))}
    health = ProviderHealth(clock=time_.clock)
    router = LLMRouter(profiles, providers, health)
    defaults = dict(max_retries=2, retry_base_seconds=1.0, cooldown_seconds=60.0,
                    quota_cooldown_seconds=3600.0, total_deadline_seconds=150.0)
    defaults.update(policy)
    return LLMGateway(router, GatewayPolicy(**defaults),
                      sleep=time_.sleep, clock=time_.clock, jitter=lambda: 0.0)


def make_request(**overrides) -> LLMRequest[Answer]:
    fields = dict(skill="test_skill", profile=PROFILE, instructions="Summarise.",
                  input={"evidence": SECRET_INPUT}, output_schema=Answer)
    fields.update(overrides)
    return LLMRequest(**fields)


def models_called(providers) -> list[str]:
    return [call.model for p in providers.values() for call in p.calls]


# ── Success and validation ────────────────────────────────────────────────────

async def test_returns_validated_output_and_where_it_came_from(providers, time_):
    providers["p1"].script("model-a", [GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())

    assert result.output == Answer(**GOOD)
    assert (result.provider, result.model) == ("p1", "model-a")
    assert [a.outcome for a in result.attempts] == ["ok"]
    assert result.usage.output_tokens > 0
    assert result.fallback_used is False


async def test_sends_instructions_input_and_strict_schema(providers, time_):
    providers["p1"].script("model-a", [GOOD])
    await make_gateway(providers, time_).generate_structured(make_request())

    [call] = providers["p1"].calls
    assert call.instructions == "Summarise."
    assert SECRET_INPUT in call.input_json
    assert call.schema_name == "Answer"
    assert call.json_schema == strict_json_schema(Answer)
    assert call.strict_schema is True
    assert call.repair_feedback is None


async def test_invalid_reply_is_repaired_once(providers, time_):
    providers["p1"].script("model-a", [{"title": "", "score": "lots"}, GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())

    assert result.output.title == "Vessel anomalies"
    first, second = providers["p1"].calls
    assert first.repair_feedback is None
    assert "did not match the required JSON schema" in second.repair_feedback
    assert "title" in second.repair_feedback
    assert [a.outcome for a in result.attempts] == ["invalid_output", "ok"]


async def test_broken_json_is_repaired_once(providers, time_):
    providers["p1"].script("model-a", ["{not json", GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())
    assert result.output == Answer(**GOOD)


async def test_still_invalid_after_repair_falls_back(providers, time_):
    providers["p1"].script("model-a", ["{bad", "{still bad"])
    providers["p1"].script("model-b", [GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())

    assert result.model == "model-b"
    assert result.fallback_used is True
    assert models_called(providers) == ["model-a", "model-a", "model-b"]


async def test_provider_reported_invalid_output_is_repaired(providers, time_):
    providers["p1"].script("model-a", [LLMInvalidOutput("schema mismatch"), GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())
    assert result.model == "model-a"
    assert providers["p1"].calls[1].repair_feedback


# ── Short-lived failures: retry, then fall back ───────────────────────────────

async def test_rate_limit_waits_as_asked_then_succeeds(providers, time_):
    providers["p1"].script("model-a", [LLMRateLimited("busy", retry_after=7), GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())

    assert result.model == "model-a"
    assert time_.sleeps == [7]


async def test_retries_use_growing_pauses(providers, time_):
    providers["p1"].script("model-a", [LLMServerError("500"), LLMServerError("502"), GOOD])
    await make_gateway(providers, time_).generate_structured(make_request())
    assert time_.sleeps == [1.0, 2.0]


async def test_rate_limit_after_retries_cools_down_and_falls_back(providers, time_):
    providers["p1"].script("model-a", [LLMRateLimited("busy")] * 3)
    providers["p1"].script("model-b", [GOOD, GOOD])
    gateway = make_gateway(providers, time_)

    result = await gateway.generate_structured(make_request())
    assert result.model == "model-b"
    assert models_called(providers) == ["model-a"] * 3 + ["model-b"]

    # The next request skips the cooling-down model entirely.
    await gateway.generate_structured(make_request())
    assert models_called(providers)[-1] == "model-b"
    assert models_called(providers).count("model-a") == 3


async def test_cooled_down_route_is_used_again_later(providers, time_):
    providers["p1"].script("model-a", [LLMRateLimited("busy")] * 3 + [GOOD])
    providers["p1"].script("model-b", [GOOD])
    gateway = make_gateway(providers, time_)
    await gateway.generate_structured(make_request())

    time_.now += 61          # cooldown is 60 s
    result = await gateway.generate_structured(make_request())
    assert result.model == "model-a"


async def test_timeouts_are_retried_then_fall_back(providers, time_):
    providers["p1"].script("model-a", [LLMTimeout("slow")] * 3)
    providers["p1"].script("model-b", [GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())

    assert result.model == "model-b"
    assert [a.outcome for a in result.attempts] == ["timeout"] * 3 + ["ok"]


async def test_repeated_server_errors_cool_the_route_down(providers, time_):
    # Three requests in a row each end with model-a failing → it cools down.
    for _ in range(3):
        providers["p1"].script("model-a", [LLMServerError("500")] * 3)
        providers["p1"].script("model-b", [GOOD])
    gateway = make_gateway(providers, time_)
    for _ in range(3):
        await gateway.generate_structured(make_request())
    assert gateway.router.health.is_usable(A) is False


# ── Failures that skip retrying ───────────────────────────────────────────────

async def test_quota_falls_back_without_retrying_and_cools_down_long(providers, time_):
    providers["p1"].script("model-a", [LLMQuotaExhausted("tokens per day")])
    providers["p1"].script("model-b", [GOOD])
    gateway = make_gateway(providers, time_)

    result = await gateway.generate_structured(make_request())
    assert result.model == "model-b"
    assert time_.sleeps == []

    time_.now += 120          # longer than a normal cooldown, shorter than the quota one
    assert gateway.router.health.is_usable(A) is False


async def test_invalid_key_makes_the_whole_provider_unavailable(providers, time_):
    providers["p1"].script("model-a", [LLMAuthError("401")])
    providers["p2"].script("model-c", [GOOD])
    result = await make_gateway(providers, time_).generate_structured(make_request())

    # model-b is on the same provider, so it is skipped too.
    assert result.model == "model-c"
    assert models_called(providers) == ["model-a", "model-c"]


async def test_context_too_long_only_falls_back_to_a_bigger_model(providers, time_):
    small, same, bigger = route("p1", "small", 50_000), route("p1", "same", 50_000), route("p2", "big", 200_000)
    providers["p1"].script("small", [LLMContextTooLong("too long")])
    providers["p2"].script("big", [GOOD])
    gateway = make_gateway(providers, time_, routes=(small, same, bigger))

    result = await gateway.generate_structured(make_request())
    assert result.model == "big"
    assert models_called(providers) == ["small", "big"]


async def test_routes_too_small_for_the_input_are_skipped_up_front(providers, time_):
    tiny = route("p1", "tiny", context=100)
    providers["p2"].script("model-c", [GOOD])
    gateway = make_gateway(providers, time_, routes=(tiny, C))

    result = await gateway.generate_structured(make_request(input={"evidence": "x" * 2_000}))
    assert result.model == "model-c"
    assert models_called(providers) == ["model-c"]


# ── Never fall back ───────────────────────────────────────────────────────────

async def test_safety_refusal_is_never_sent_to_another_model(providers, time_):
    providers["p1"].script("model-a", [LLMRefusal("declined")])
    providers["p1"].script("model-b", [GOOD])

    with pytest.raises(LLMRefusal):
        await make_gateway(providers, time_).generate_structured(make_request())
    assert models_called(providers) == ["model-a"]


async def test_bad_request_is_not_retried_or_sent_elsewhere(providers, time_):
    providers["p1"].script("model-a", [LLMBadRequest("bad parameter")])
    with pytest.raises(LLMBadRequest):
        await make_gateway(providers, time_).generate_structured(make_request())
    assert models_called(providers) == ["model-a"]


# ── Nothing works ─────────────────────────────────────────────────────────────

async def test_all_routes_failing_raises_unavailable_with_causes(providers, time_):
    providers["p1"].script("model-a", [LLMQuotaExhausted("daily")])
    providers["p1"].script("model-b", [LLMAuthError("401")])
    providers["p2"].script("model-c", ["{bad", "{bad"])

    with pytest.raises(LLMUnavailable) as caught:
        await make_gateway(providers, time_).generate_structured(make_request())
    assert caught.value.causes == ["quota_exhausted", "auth_error", "invalid_output", "invalid_output"]


async def test_no_configured_provider_raises_unavailable(time_):
    gateway = make_gateway({}, time_)
    with pytest.raises(LLMUnavailable, match="no usable model"):
        await gateway.generate_structured(make_request())


async def test_total_deadline_stops_retrying(providers, time_):
    providers["p1"].script("model-a", [LLMRateLimited("busy", retry_after=20)] * 3)
    providers["p1"].script("model-b", [GOOD])
    gateway = make_gateway(providers, time_, total_deadline_seconds=30)

    result = await gateway.generate_structured(make_request())
    # One 20 s pause fits in 30 s; a second would not, so it falls back instead.
    assert time_.sleeps == [20]
    assert result.model == "model-b"


async def test_unknown_profile_is_a_programming_error(providers, time_):
    with pytest.raises(ValueError, match="Unknown LLM profile"):
        await make_gateway(providers, time_).generate_structured(make_request(profile="nope"))


# ── Logging ───────────────────────────────────────────────────────────────────

async def test_logs_each_attempt_without_prompt_or_input(providers, time_, caplog):
    providers["p1"].script("model-a", [LLMTimeout("slow"), GOOD])
    with caplog.at_level(logging.INFO, logger="grey.llm"):
        await make_gateway(providers, time_).generate_structured(make_request())

    lines = [r.getMessage() for r in caplog.records if r.name == "grey.llm"]
    assert len(lines) == 2
    assert "skill=test_skill" in lines[0] and "outcome=timeout" in lines[0]
    assert "provider=p1 model=model-a outcome=ok" in lines[1]
    assert all(SECRET_INPUT not in line and "Summarise." not in line for line in lines)


# ── Strict schema conversion ──────────────────────────────────────────────────

class Inner(BaseModel):
    ref: str = Field(min_length=1)
    note: str = "default"


class Outer(BaseModel):
    items: list[Inner] = Field(min_length=1, max_length=5)
    name: str


def test_strict_schema_inlines_references_and_requires_every_field():
    schema = strict_json_schema(Outer)
    text = str(schema)

    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["items", "name"]
    item = schema["properties"]["items"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["ref", "note"]
    for keyword in ("minLength", "maxLength", "minItems", "maxItems", "default", "title"):
        assert keyword not in text


def test_strict_schema_keeps_fields_named_like_keywords():
    # A field called "title" was dropped with the "title" keyword, so Groq never
    # sent it and every reply failed validation (live run, 2026-10-06).
    schema = strict_json_schema(Answer)

    assert list(schema["properties"]) == ["title", "score"]
    assert schema["required"] == ["title", "score"]
    assert "title" not in schema["properties"]["title"]      # the keyword is still removed


def test_problem_draft_schema_asks_for_a_title():
    from app.domains.fyp.skills.problem_extraction.schemas import LLMProblemDrafts

    draft = strict_json_schema(LLMProblemDrafts)["properties"]["problems"]["items"]
    assert "title" in draft["properties"] and "title" in draft["required"]
