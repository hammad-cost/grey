"""
Types for the assess_feasibility skill (Release 0.12).

  LLM-facing   — LLMFeasibilityDraft: only the JUDGEMENT dimensions, the main risks
                 and a summary (the FACT dimensions and the overall rating come from code).
  Grey-facing  — AssessFeasibilityInput / Output.
  Progress     — FeasibilityPhase / FeasibilityProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategy,
    DatasetOption,
    EvidenceTier,
    FeasibilityDimension,
    FeasibilityReport,
    FYPDesign,
    ModelPlan,
    ProjectDefinition,
    TechnicalPlan,
    TechnologyPlan,
)
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief

# Judged by the model; every other dimension is computed from facts in the Project Brain (facts.py).
JUDGEMENT_DIMENSIONS = [
    FeasibilityDimension.PROBLEM_RELEVANCE,
    FeasibilityDimension.TECHNICAL_COMPLEXITY,
    FeasibilityDimension.TIME,
    FeasibilityDimension.EXTERNAL_DEPENDENCIES,
    FeasibilityDimension.ETHICAL_LEGAL,
    FeasibilityDimension.RISK,
    FeasibilityDimension.NOVELTY,
]


class AssessFeasibilityInput(BaseModel):
    """The student's approved decisions, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    problem: ProblemBrief
    evidence_tiers: list[EvidenceTier]           # the tiers of the sources behind the chosen problem
    design: FYPDesign
    definition: ProjectDefinition
    strategy: AIStrategy
    dataset: DatasetOption
    models: ModelPlan
    technology: TechnologyPlan
    technical: TechnicalPlan


class AssessFeasibilityOutput(BaseModel):
    report: FeasibilityReport
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}


class LLMJudgementDraft(BaseModel):
    dimension: str
    level: str          # favourable | moderate | concern
    finding: str
    reason: str


class LLMRiskDraft(BaseModel):
    risk: str
    mitigation: str


class LLMFeasibilityDraft(BaseModel):
    summary: str
    judgements: list[LLMJudgementDraft]
    main_risks: list[LLMRiskDraft]


class FeasibilityPhase(str, Enum):
    FACTS = "checking_facts"
    JUDGING = "judging_feasibility"
    CHECKING = "checking_feasibility"


class FeasibilityProgress(BaseModel):
    phase: FeasibilityPhase
    label: str


FeasibilityProgressCallback = Callable[[FeasibilityProgress], Awaitable[None]]
