r"""
Live test: the generate_proposal skill (Release 0.14) with a real Groq model.

Writes the full proposal for the sample navy project (three small "writing" calls)
and checks it follows Grey's rules (sections in order, citations only to real
sources). Costs 3-6 Groq calls, so it is SKIPPED unless:

    $env:RUN_LIVE_LLM_TESTS = "1"
    .\venv\Scripts\python.exe -m pytest tests/live/test_proposal_live.py -s
"""
import os

import pytest

from app.core.brain.proposal_rules import proposal_rule_broken
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.domains.fyp.skills.generate_proposal import GenerateProposalInput, GenerateProposalSkill, proposal_markdown
from tests.unit.test_prepare_supervisor_brief_skill import brief_input

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="set RUN_LIVE_LLM_TESTS=1 to call Groq"),
]


async def test_groq_writes_a_traceable_proposal():
    settings = Settings(llm_mode="live")          # key comes from Backend/.env
    if not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY is not set in Backend/.env")

    output = await GenerateProposalSkill(build_llm_gateway(settings)).execute(GenerateProposalInput(decisions=brief_input()))

    print(f"\n{output.provider}/{output.model} rejected={output.rejection_summary}\n")
    print(proposal_markdown(output.proposal).encode("ascii", "backslashreplace").decode())
    assert output.provider == "groq"
    assert proposal_rule_broken(output.proposal) is None
