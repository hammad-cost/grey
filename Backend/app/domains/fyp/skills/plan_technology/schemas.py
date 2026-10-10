"""
Types for the plan_technology skill (Release 0.10).

  LLM-facing   — LLMTechnologyPlanDraft: the shape the model must return
                 (checked by validation.py before it is trusted).
  Grey-facing  — PlanTechnologyInput / Output.
  Progress     — TechnologyPhase / TechnologyProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategy,
    DatasetOption,
    FunctionalArea,
    FYPDesign,
    ModelPlan,
    ProjectDefinition,
    TechnologyPlan,
    TechnologyPreference,
)
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief


class PlanTechnologyInput(BaseModel):
    """The student's approved decisions so far, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    design: FYPDesign
    definition: ProjectDefinition
    strategy: AIStrategy
    dataset: DatasetOption
    models: ModelPlan
    preference: TechnologyPreference | None = None
    previous_plan: TechnologyPlan | None = None


class PlanTechnologyOutput(BaseModel):
    plan: TechnologyPlan
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}


class LLMStackChoiceDraft(BaseModel):
    area: str           # frontend | backend | database | ai_ml | training | deployment
    choice: str
    reason: str


class LLMHardwareDraft(BaseModel):
    kind: str           # normal_laptop | dedicated_gpu | google_colab | cloud_gpu | camera | sensors | …
    name: str
    purpose: str
    essential: bool
    cost: str           # none | low | medium | high
    alternative: str    # "" when there is none


class LLMTechnologyPlanDraft(BaseModel):
    summary: str
    stack: list[LLMStackChoiceDraft]
    hardware: list[LLMHardwareDraft]


class TechnologyPhase(str, Enum):
    PLANNING = "planning_technology"
    CHECKING = "checking_technology"


class TechnologyProgress(BaseModel):
    phase: TechnologyPhase
    label: str


TechnologyProgressCallback = Callable[[TechnologyProgress], Awaitable[None]]
