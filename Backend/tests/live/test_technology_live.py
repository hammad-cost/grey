r"""
Live test: the plan_technology skill (Release 0.10) with a real Groq model.

Plans the technology for the sample navy project, then asks for a simpler plan,
and checks both pass Grey's rules. Costs 2-4 Groq calls, so it is SKIPPED unless:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_technology_live.py -s
"""
import os

import pytest

from app.core.brain.schemas import TechnologyPreference
from app.core.brain.technology_rules import plan_rule_broken
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.domains.fyp.skills.plan_technology import PlanTechnologySkill
from tests.unit.test_plan_technology_skill import tech_input

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


def _show(label, output) -> None:
    print(f"\n{label}: {output.provider}/{output.model} rejected={output.rejection_summary}")
    print(output.plan.model_dump_json(indent=2).encode("ascii", "backslashreplace").decode())


async def test_groq_plans_the_technology_and_a_simpler_version():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")
    skill = PlanTechnologySkill(build_llm_gateway(settings))

    first = await skill.execute(tech_input())
    _show("first", first)
    assert first.provider == "groq"
    assert plan_rule_broken(first.plan, uses_ai=True) is None

    simpler = await skill.execute(tech_input(TechnologyPreference.SIMPLER, first.plan))
    _show("simpler", simpler)
    assert plan_rule_broken(simpler.plan, uses_ai=True) is None
