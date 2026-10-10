"""
FYP skills.

register_fyp_skills() puts every FYP skill into a SkillRegistry.
It is called once at application startup (and by tests with their own registry),
so workflows look skills up by name instead of creating them directly.
"""
from app.core.llm import LLMGateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.search import SearchProvider
from app.domains.fyp.skills.classify_area import ClassifyAreaSkill
from app.domains.fyp.skills.classify_area.fake import install_fake_answers as install_fake_area_answers
from app.domains.fyp.skills.define_project import DefineProjectSkill
from app.domains.fyp.skills.define_project.fake import install_fake_answers as install_fake_definition_answers
from app.domains.fyp.skills.design_fyp import DesignFYPSkill
from app.domains.fyp.skills.design_fyp.fake import install_fake_answers as install_fake_design_answers
from app.domains.fyp.skills.find_datasets import FindDatasetsSkill
from app.domains.fyp.skills.find_datasets.fake import install_fake_answers as install_fake_dataset_answers
from app.domains.fyp.skills.plan_ai_strategy import PlanAIStrategySkill
from app.domains.fyp.skills.plan_ai_strategy.fake import install_fake_answers as install_fake_strategy_answers
from app.domains.fyp.skills.problem_extraction import ProblemExtractionSkill
from app.domains.fyp.skills.problem_extraction.fake import install_fake_answers
from app.domains.fyp.skills.research_evidence import ResearchEvidenceSkill


def register_fyp_skills(
    registry: SkillRegistry,
    search: SearchProvider,
    llm: LLMGateway | None = None,
    max_searches: int = 15,
    max_dataset_searches: int = 6,
) -> None:
    """
    Register all FYP skills, giving each one the tools it needs.

    The skills that use the LLM gateway (problem extraction, the Release 0.5
    classify_area and design_fyp, the Release 0.6 define_project, the
    Release 0.7 plan_ai_strategy and the Release 0.8 find_datasets, which also
    searches) are only registered when one is given. In fake mode, the fake
    provider is also taught how to answer them.
    """
    registry.register(ResearchEvidenceSkill(search, max_searches=max_searches))
    if llm is not None:
        install_fake_answers(llm)
        registry.register(ProblemExtractionSkill(llm))
        install_fake_area_answers(llm)
        registry.register(ClassifyAreaSkill(llm))
        install_fake_design_answers(llm)
        registry.register(DesignFYPSkill(llm))
        install_fake_definition_answers(llm)
        registry.register(DefineProjectSkill(llm))
        install_fake_strategy_answers(llm)
        registry.register(PlanAIStrategySkill(llm))
        install_fake_dataset_answers(llm)
        registry.register(FindDatasetsSkill(search, llm, max_searches=max_dataset_searches))
