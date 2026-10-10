r"""
Live test: the design_architecture skill (Release 0.11) with a real Groq model.

Designs the architecture and evaluation plan for the sample navy project and
checks it passes Grey's rules. Costs 1-2 Groq calls, so it is SKIPPED unless:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_architecture_live.py -s
"""
import os

import pytest

from app.core.brain.architecture_rules import plan_rule_broken
from app.core.brain.schemas import AITaskType
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.domains.fyp.skills.design_architecture import DesignArchitectureSkill
from tests.unit.test_design_architecture_skill import arch_input

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


async def test_groq_designs_a_consistent_architecture_and_evaluation_plan():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")

    output = await DesignArchitectureSkill(build_llm_gateway(settings)).execute(arch_input())

    print(f"\n{output.provider}/{output.model} rejected={output.rejection_summary}")
    print(output.plan.model_dump_json(indent=2).encode("ascii", "backslashreplace").decode())
    assert output.provider == "groq"
    assert plan_rule_broken(output.plan, uses_ai=True, task=AITaskType.ANOMALY_DETECTION) is None
