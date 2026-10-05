"""
FYP skills.

register_fyp_skills() puts every FYP skill into a SkillRegistry.
It is called once at application startup (and by tests with their own registry),
so workflows look skills up by name instead of creating them directly.
"""
from app.core.llm import LLMGateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.search import SearchProvider
from app.domains.fyp.skills.problem_extraction import ProblemExtractionSkill
from app.domains.fyp.skills.problem_extraction.fake import install_fake_answers
from app.domains.fyp.skills.research_evidence import ResearchEvidenceSkill


def register_fyp_skills(
    registry: SkillRegistry,
    search: SearchProvider,
    llm: LLMGateway | None = None,
    max_searches: int = 15,
) -> None:
    """
    Register all FYP skills, giving each one the tools it needs.

    The Problem Extraction skill needs the LLM gateway, so it is only
    registered when one is given. In fake mode, the fake provider is also
    taught how to answer it.
    """
    registry.register(ResearchEvidenceSkill(search, max_searches=max_searches))
    if llm is not None:
        install_fake_answers(llm)
        registry.register(ProblemExtractionSkill(llm))
