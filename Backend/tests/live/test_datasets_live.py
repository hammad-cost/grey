r"""
Live test: the find_datasets skill (Release 0.8) with real search and a real Groq model.

Runs the skill on the sample navy project — the first search (4 searches through
SerpAPI / Tavily, then Groq chooses two datasets), then an "I'd rather create or
collect my own data" re-search (reuses the pages, so no new searches) — and checks
both answers pass Grey's rules. Costs about 4 search credits and 2–4 Groq calls,
so it is SKIPPED unless you ask for both:

    $env:RUN_LIVE_SEARCH_TESTS = "1"; $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_datasets_live.py -s

It needs SERPAPI_API_KEY and/or TAVILY_API_KEY, and GROQ_API_KEY, in Backend/.env.
"""
import os

import pytest

from app.core.brain.dataset_rules import plan_rule_broken
from app.core.brain.schemas import DatasetKind, DatasetPreference
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.core.tools.factory import get_search_provider
from app.domains.fyp.skills.find_datasets import FindDatasetsSkill
from app.domains.fyp.skills.find_datasets.search import is_dataset_page
from tests.unit.test_find_datasets_skill import dataset_input

pytestmark = [
    pytest.mark.live_search,
    pytest.mark.live_llm,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_SEARCH_TESTS") != "1" or os.getenv("RUN_LIVE_LLM_TESTS") != "1",
        reason="set RUN_LIVE_SEARCH_TESTS=1 and RUN_LIVE_LLM_TESTS=1 to call real search and Groq",
    ),
]


def _show(label, output) -> None:
    print(f"\n{label}: {output.provider}/{output.model} searches={output.searches_used} "
          f"pages={len(output.candidates)} rejected={output.rejection_summary}")
    for n, page in enumerate(output.candidates, start=1):
        print(f"  {n}. [{page.provider}] {page.title}\n     {page.url}")
    # ASCII-only, so the Windows console can print every character the model writes.
    print(output.plan.model_dump_json(indent=2).encode("ascii", "backslashreplace").decode())


async def test_real_search_and_groq_recommend_two_honest_datasets():
    settings = Settings(llm_mode="live", search_providers="serpapi,tavily")   # keys come from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")
    if not (settings.serpapi_api_key.get_secret_value() or settings.tavily_api_key.get_secret_value()):
        pytest.skip("No search key is set in Backend/.env")
    skill = FindDatasetsSkill(get_search_provider(settings), build_llm_gateway(settings), max_searches=4)

    first = await skill.execute(dataset_input())
    _show("first", first)
    assert first.provider == "groq"
    assert first.searches_used == 4
    assert all(is_dataset_page(page.url) for page in first.candidates)
    assert plan_rule_broken(first.plan, {page.url for page in first.candidates}) is None

    own = await skill.execute(dataset_input(DatasetPreference.OWN_DATA, first.plan, known=first.candidates))
    _show("own data", own)
    assert own.searches_used == 0
    assert own.plan.primary.kind in (DatasetKind.SYNTHETIC, DatasetKind.STUDENT_COLLECTED)
    assert plan_rule_broken(
        own.plan, {page.url for page in own.candidates}, preference=DatasetPreference.OWN_DATA, previous=first.plan
    ) is None
