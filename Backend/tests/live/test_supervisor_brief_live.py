r"""
Live test: the prepare_supervisor_brief skill (Release 0.13) with a real Groq model.

Prepares the brief for the sample navy project and checks every question gets
talking points. Costs 1-2 Groq calls, so it is SKIPPED unless:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_supervisor_brief_live.py -s
"""
import os

import pytest

from app.core.brain.supervisor_rules import brief_rule_broken
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.domains.fyp.skills.prepare_supervisor_brief import PrepareSupervisorBriefSkill
from tests.unit.test_prepare_supervisor_brief_skill import brief_input

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


async def test_groq_writes_talking_points_for_every_question():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")

    output = await PrepareSupervisorBriefSkill(build_llm_gateway(settings)).execute(brief_input())

    print(f"\n{output.provider}/{output.model} rejected={output.rejection_summary}")
    for q in output.brief.questions:
        print(f"\n{q.question}".encode("ascii", "backslashreplace").decode())
        for point in q.talking_points:
            print(f"  - {point}".encode("ascii", "backslashreplace").decode())
    assert output.provider == "groq"
    assert brief_rule_broken(output.brief) is None
