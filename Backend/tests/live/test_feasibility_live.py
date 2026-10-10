r"""
Live test: the assess_feasibility skill (Release 0.12) with a real Groq model.

Assesses the sample navy project and checks the report passes Grey's rules (the
overall rating is computed in code). Costs 1-2 Groq calls, so it is SKIPPED unless:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_feasibility_live.py -s
"""
import os

import pytest

from app.core.brain.feasibility_rules import report_rule_broken
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.domains.fyp.skills.assess_feasibility import AssessFeasibilitySkill
from tests.unit.test_assess_feasibility_skill import feasibility_input

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


async def test_groq_judges_feasibility_honestly():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")

    output = await AssessFeasibilitySkill(build_llm_gateway(settings)).execute(feasibility_input())

    print(f"\n{output.provider}/{output.model} rejected={output.rejection_summary}")
    print(output.report.model_dump_json(indent=2).encode("ascii", "backslashreplace").decode())
    assert output.provider == "groq"
    assert report_rule_broken(output.report) is None
