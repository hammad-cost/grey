r"""
Live test: the find_models skill (Release 0.9) with real search and a real Groq model.

Runs one model search for the sample navy project (4 searches through SerpAPI /
Tavily, then Groq chooses 0-3 pages) and checks the answer passes Grey's rules.
Costs about 4 search credits and 1-2 Groq calls, so it is SKIPPED unless you ask:

    $env:RUN_LIVE_SEARCH_TESTS = "1"; $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_models_live.py -s
"""
import os

import pytest

from app.core.brain.model_rules import plan_rule_broken
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.core.tools.factory import get_search_provider
from app.domains.fyp.skills.find_models import FindModelsSkill
from app.domains.fyp.skills.find_models.search import is_model_page
from tests.unit.test_find_models_skill import model_input

pytestmark = [
    pytest.mark.live_search,
    pytest.mark.live_llm,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_SEARCH_TESTS") != "1" or os.getenv("RUN_LIVE_LLM_TESTS") != "1",
        reason="set RUN_LIVE_SEARCH_TESTS=1 and RUN_LIVE_LLM_TESTS=1 to call real search and Groq",
    ),
]


async def test_real_search_and_groq_give_an_honest_model_plan():
    settings = Settings(llm_mode="live", search_providers="serpapi,tavily")   # keys come from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")
    skill = FindModelsSkill(get_search_provider(settings), build_llm_gateway(settings), max_searches=4)

    output = await skill.execute(model_input())

    print(f"\n{output.provider}/{output.model} searches={output.searches_used} "
          f"pages={len(output.candidates)} rejected={output.rejection_summary}")
    for n, page in enumerate(output.candidates, start=1):
        print(f"  {n}. {page.title}\n     {page.url}".encode("ascii", "replace").decode())
    # ASCII-only, so the Windows console can print every character the model writes.
    print(output.plan.model_dump_json(indent=2).encode("ascii", "backslashreplace").decode())
    assert output.provider == "groq"
    assert all(is_model_page(page.url) for page in output.candidates)
    assert plan_rule_broken(output.plan, {page.url for page in output.candidates}) is None
