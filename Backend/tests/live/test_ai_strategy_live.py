r"""
Live test: the plan_ai_strategy skill (Release 0.7) with a real Groq model.

Runs the skill on the sample navy project — the first check, then a
"Can I do this without AI?" re-check — and checks both answers pass Grey's
rules. Costs a little of your Groq quota (2–4 calls), so it is SKIPPED unless
you ask for it:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_ai_strategy_live.py -s

It needs GROQ_API_KEY in Backend/.env. No search provider is used.
"""
import os

import pytest

from app.core.brain.ai_strategy_rules import strategy_rule_broken
from app.core.brain.schemas import AIStrategyPreference
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.domains.fyp.skills.plan_ai_strategy import PlanAIStrategySkill
from tests.unit.test_plan_ai_strategy_skill import strategy_input

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


async def test_groq_checks_the_ai_need_and_rechecks_without_ai():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")
    skill = PlanAIStrategySkill(build_llm_gateway(settings))

    first = await skill.execute(strategy_input())
    print(f"\nfirst:   {first.provider}/{first.model} rejected={first.rejection_summary}")
    print(first.strategy.model_dump_json(indent=2))
    assert first.provider == "groq"
    assert strategy_rule_broken(first.strategy) is None

    again = await skill.execute(strategy_input(AIStrategyPreference.WITHOUT_AI, first.strategy))
    print(f"recheck: rejected={again.rejection_summary}")
    print(again.strategy.model_dump_json(indent=2))
    assert strategy_rule_broken(again.strategy) is None
