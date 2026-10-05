"""
Tests for the provider adapters.

OpenAICompatibleProvider (used for Groq) is tested against a fake HTTP
transport — the request never leaves the test. Checks the request format
and that every vendor error becomes the right Grey error.
"""
import json

import httpx
import pytest

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
)
from app.core.llm.providers.base import ProviderCall
from app.core.llm.providers.fake import FakeLLMProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider

API_KEY = "gsk_test_secret_key"
SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}


def make_call(**overrides) -> ProviderCall:
    fields = dict(model="openai/gpt-oss-120b", instructions="Be helpful.", input_json='{"x": 1}',
                  schema_name="Answer", json_schema=SCHEMA, strict_schema=True,
                  max_output_tokens=500, timeout_seconds=30.0)
    fields.update(overrides)
    return ProviderCall(**fields)


def provider_with(handler) -> tuple[OpenAICompatibleProvider, list[httpx.Request]]:
    """A Groq-style provider whose HTTP calls go to `handler` instead of the network."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return OpenAICompatibleProvider("groq", "https://api.groq.example/openai/v1/", API_KEY, client), seen


def ok_body(content='{"a": "yes"}', finish_reason="stop", **message) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content, **message},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def error_response(status: int, message: str, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "type": "x"}}, headers=headers)


# ── Request format ────────────────────────────────────────────────────────────

async def test_sends_chat_completion_with_strict_json_schema():
    provider, seen = provider_with(lambda r: httpx.Response(200, json=ok_body()))

    response = await provider.generate_json(make_call())

    [request] = seen
    assert str(request.url) == "https://api.groq.example/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": '{"x": 1}'},
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Answer", "strict": True, "schema": SCHEMA},
    }
    assert body["max_completion_tokens"] == 500

    assert response.text == '{"a": "yes"}'
    assert (response.input_tokens, response.output_tokens) == (120, 30)


async def test_uses_json_mode_when_the_model_cannot_enforce_the_schema():
    provider, seen = provider_with(lambda r: httpx.Response(200, json=ok_body()))
    await provider.generate_json(make_call(strict_schema=False))
    assert json.loads(seen[0].content)["response_format"] == {"type": "json_object"}


async def test_repair_feedback_is_sent_as_an_extra_message():
    provider, seen = provider_with(lambda r: httpx.Response(200, json=ok_body()))
    await provider.generate_json(make_call(repair_feedback="Fix field 'a'."))
    assert json.loads(seen[0].content)["messages"][-1] == {"role": "user", "content": "Fix field 'a'."}


# ── Error translation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "status, message, expected",
    [
        (401, "Invalid API Key", LLMAuthError),
        (403, "Forbidden", LLMAuthError),
        (429, "Rate limit reached on tokens per day (TPD)", LLMQuotaExhausted),
        (429, "insufficient_quota", LLMQuotaExhausted),
        (413, "Request too large", LLMContextTooLong),
        (400, "Please reduce the length of the messages", LLMContextTooLong),
        (400, "Generated JSON does not match the expected schema. Please adjust your prompt.", LLMInvalidOutput),
        (400, "Unknown parameter 'foo'", LLMBadRequest),
        (404, "Model not found", LLMBadRequest),
        (422, "Unprocessable", LLMBadRequest),
        (498, "Flex tier capacity exceeded", LLMServerError),
        (500, "Internal error", LLMServerError),
        (502, "Bad gateway", LLMServerError),
        (503, "Service unavailable", LLMServerError),
    ],
)
async def test_http_errors_become_grey_errors(status, message, expected):
    provider, _ = provider_with(lambda r: error_response(status, message))
    with pytest.raises(expected) as caught:
        await provider.generate_json(make_call())
    assert caught.value.provider == "groq"
    assert caught.value.model == "openai/gpt-oss-120b"


async def test_rate_limit_carries_retry_after():
    provider, _ = provider_with(
        lambda r: error_response(429, "Rate limit reached on tokens per minute", {"retry-after": "12"})
    )
    with pytest.raises(LLMRateLimited) as caught:
        await provider.generate_json(make_call())
    assert caught.value.retry_after == 12.0


async def test_timeout_becomes_llm_timeout():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    provider, _ = provider_with(slow)
    with pytest.raises(LLMTimeout):
        await provider.generate_json(make_call())


async def test_connection_problem_becomes_server_error():
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    provider, _ = provider_with(down)
    with pytest.raises(LLMServerError):
        await provider.generate_json(make_call())


async def test_refusal_is_reported_as_refusal():
    provider, _ = provider_with(lambda r: httpx.Response(200, json=ok_body(content=None, refusal="I can't help with that.")))
    with pytest.raises(LLMRefusal):
        await provider.generate_json(make_call())


async def test_content_filter_is_reported_as_refusal():
    provider, _ = provider_with(lambda r: httpx.Response(200, json=ok_body(finish_reason="content_filter")))
    with pytest.raises(LLMRefusal):
        await provider.generate_json(make_call())


async def test_cut_off_reply_is_invalid_output():
    provider, _ = provider_with(lambda r: httpx.Response(200, json=ok_body(content='{"a": "ye', finish_reason="length")))
    with pytest.raises(LLMInvalidOutput):
        await provider.generate_json(make_call())


async def test_empty_reply_is_invalid_output():
    provider, _ = provider_with(lambda r: httpx.Response(200, json=ok_body(content="")))
    with pytest.raises(LLMInvalidOutput):
        await provider.generate_json(make_call())


async def test_unreadable_response_is_server_error():
    provider, _ = provider_with(lambda r: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(LLMServerError):
        await provider.generate_json(make_call())


async def test_api_key_never_appears_in_error_messages():
    provider, _ = provider_with(lambda r: error_response(401, "Invalid API Key"))
    with pytest.raises(LLMAuthError) as caught:
        await provider.generate_json(make_call())
    assert API_KEY not in str(caught.value)


# ── FakeLLMProvider ───────────────────────────────────────────────────────────

async def test_fake_provider_follows_its_script_and_records_calls():
    fake = FakeLLMProvider()
    fake.script("m", [LLMTimeout("slow"), {"a": "yes"}, "{broken"])

    with pytest.raises(LLMTimeout):
        await fake.generate_json(make_call(model="m"))
    assert (await fake.generate_json(make_call(model="m"))).text == '{"a": "yes"}'
    assert (await fake.generate_json(make_call(model="m"))).text == "{broken"
    assert len(fake.calls) == 3


async def test_fake_provider_responder_builds_reply_from_input():
    fake = FakeLLMProvider()
    fake.add_responder("Answer", lambda data: {"a": f"x={data['x']}"})
    response = await fake.generate_json(make_call(model="any"))
    assert json.loads(response.text) == {"a": "x=1"}


async def test_fake_provider_without_a_reply_is_a_bad_request():
    with pytest.raises(LLMBadRequest):
        await FakeLLMProvider().generate_json(make_call(model="unscripted"))
