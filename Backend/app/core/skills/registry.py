"""
SkillRegistry

A central catalog of all registered skills.
Workflows and future agents look up skills by name through this registry.

Why a registry instead of direct imports?
  - Discoverability: one place to see every skill Grey knows.
  - Consistent logging and cost attribution per skill.
  - Easy future path: replace a skill entry with a specialist agent
    and the calling workflow does not change.

The registry is intentionally simple in the MVP — it is a dict with
a lookup method, not a dynamic plugin system.
"""
from app.core.skills.base import Skill


class SkillRegistry:
    """
    Stores and retrieves Skill instances by name.

    Usage:
        registry = SkillRegistry()
        registry.register(ResearchEvidenceSkill())
        skill = registry.get("research_evidence")
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """
        Add a skill to the registry.
        Raises ValueError if a skill with the same name is already registered,
        to prevent accidental overwrites.
        """
        name = skill.metadata.name
        if name in self._skills:
            raise ValueError(
                f"Skill '{name}' is already registered. "
                "Use a different name or deregister the existing skill first."
            )
        self._skills[name] = skill

    def get(self, name: str) -> Skill:
        """
        Return the skill registered under `name`.
        Raises KeyError if no skill with that name exists.
        """
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(
                f"Skill '{name}' is not registered. "
                f"Registered skills: {self.list_skills()}"
            )
        return skill

    def list_skills(self) -> list[str]:
        """Return the names of all registered skills."""
        return sorted(self._skills.keys())

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# Global shared registry instance.
# Workflows and the orchestrator import this directly.
# Skills register themselves here during application startup.
skill_registry = SkillRegistry()
