"""
FYP skills.

register_fyp_skills() puts every FYP skill into a SkillRegistry.
It is called once at application startup (and by tests with their own registry),
so workflows look skills up by name instead of creating them directly.
"""
from app.core.skills.registry import SkillRegistry
from app.core.tools.search import SearchProvider
from app.domains.fyp.skills.research_evidence import ResearchEvidenceSkill


def register_fyp_skills(registry: SkillRegistry, search: SearchProvider) -> None:
    """Register all FYP skills, giving each one the tools it needs."""
    registry.register(ResearchEvidenceSkill(search))
