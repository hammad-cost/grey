"""
Types for the design_architecture skill (Release 0.11).

  LLM-facing   — LLMTechnicalPlanDraft (checked by validation.py before it is trusted).
  Grey-facing  — DesignArchitectureInput / Output.
  Progress     — ArchitecturePhase / ArchitectureProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategy,
    ArchitecturePreference,
    DatasetOption,
    FYPDesign,
    ModelPlan,
    ProjectDefinition,
    TechnicalPlan,
    TechnologyPlan,
)
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief


class DesignArchitectureInput(BaseModel):
    """The student's approved decisions so far, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    problem: ProblemBrief
    design: FYPDesign
    definition: ProjectDefinition
    strategy: AIStrategy
    dataset: DatasetOption
    models: ModelPlan
    technology: TechnologyPlan
    preference: ArchitecturePreference | None = None
    previous_plan: TechnicalPlan | None = None


class DesignArchitectureOutput(BaseModel):
    plan: TechnicalPlan
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}


class LLMComponentDraft(BaseModel):
    id: str
    name: str
    kind: str
    role: str
    technology: str          # "" when none


class LLMFlowDraft(BaseModel):
    source: str
    target: str
    data: str


class LLMMetricDraft(BaseModel):
    metric: str
    why: str
    goal: str


class LLMTestDraft(BaseModel):
    kind: str
    how: str


class LLMTechnicalPlanDraft(BaseModel):
    summary: str
    components: list[LLMComponentDraft]
    flows: list[LLMFlowDraft]
    metrics: list[LLMMetricDraft]
    tests: list[LLMTestDraft]
    baseline: str            # "" when there is none


class ArchitecturePhase(str, Enum):
    DESIGNING = "designing_architecture"
    CHECKING = "checking_architecture"


class ArchitectureProgress(BaseModel):
    phase: ArchitecturePhase
    label: str


ArchitectureProgressCallback = Callable[[ArchitectureProgress], Awaitable[None]]
