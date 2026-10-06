"""
Types for the classify_area skill (Release 0.5).

  LLM-facing   — LLMAreaDraft: the shape the model must return. Not trusted
                 until the checks in skill.py have passed.
  Grey-facing  — ClassifyAreaInput / Output: what the workflow sends and gets back.
"""
from pydantic import BaseModel, Field

from app.core.brain.schemas import FunctionalArea
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief


class ClassifyAreaInput(BaseModel):
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    problem: ProblemBrief


class ClassifyAreaOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    area: FunctionalArea
    provider: str
    model: str
    prompt_version: str


class LLMAreaDraft(BaseModel):
    """The whole reply the model must return."""
    functional_area: str = Field(min_length=1)
    specific_area: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
