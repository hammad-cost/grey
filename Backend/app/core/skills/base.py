"""
Skill base protocol.

A Skill is the main reusable intelligent unit in Grey.
Every skill must follow this contract so it can be:
  - called from a LangGraph workflow node
  - called from a test in isolation
  - replaced later by a specialist agent without changing the caller

Rules (from the backend blueprint):
  - A skill validates its input before doing any work.
  - A skill loads only the Brain context it actually needs.
  - A skill returns a validated, typed output.
  - A skill does NOT decide what happens next in the workflow.
  - A skill does NOT silently approve major decisions.
  - A skill does NOT know which screen the student is looking at.
"""
from abc import ABC, abstractmethod

from pydantic import BaseModel


class SkillMetadata(BaseModel):
    """
    Describes a skill. Stored in the registry alongside the skill instance.
    Used for logging, cost attribution, and discoverability.
    """
    name: str                           # unique identifier, e.g. "research_evidence"
    description: str                    # one sentence explaining what the skill does
    version: str = "0.1.0"
    requires_human_approval: bool = False  # normally False; the workflow decides HITL


class Skill(ABC):
    """
    Abstract base class for all Grey skills.

    Subclass this to create a skill:

        class ResearchEvidenceSkill(Skill):
            metadata = SkillMetadata(
                name="research_evidence",
                description="Research real-world evidence for a given industry and branch.",
            )

            async def execute(self, input: ResearchEvidenceInput) -> ResearchEvidenceOutput:
                ...
    """

    metadata: SkillMetadata

    @abstractmethod
    async def execute(self, input: BaseModel) -> BaseModel:
        """
        Run the skill.

        The workflow calls this method and passes a typed input.
        The skill returns a typed output.
        The workflow then decides what to do with the result.
        """
        ...

    def __repr__(self) -> str:
        return f"<Skill name={self.metadata.name!r} version={self.metadata.version!r}>"
