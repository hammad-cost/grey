"""
Live test: one real call to Groq through the LLM gateway.

Costs a little of your Groq quota, so it is SKIPPED unless you ask for it:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest -m live_llm -s

It needs GROQ_API_KEY in Backend/.env.
"""
import os

import pytest
from pydantic import BaseModel, Field

from app.core.config.settings import Settings
from app.core.llm import STRUCTURED_REASONING, LLMRequest, build_llm_gateway

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


class Capital(BaseModel):
    country: str = Field(min_length=1)
    capital: str = Field(min_length=1)


async def test_groq_returns_validated_structured_output():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")

    gateway = build_llm_gateway(settings)
    result = await gateway.generate_structured(LLMRequest(
        skill="live_test",
        profile=STRUCTURED_REASONING,
        instructions="Answer with JSON only.",
        input={"question": "What is the capital of France?"},
        output_schema=Capital,
        max_output_tokens=1_000,
    ))

    print(f"\nprovider={result.provider} model={result.model} usage={result.usage} attempts={result.attempts}")
    assert result.provider == "groq"
    assert result.output.capital.lower() == "paris"
