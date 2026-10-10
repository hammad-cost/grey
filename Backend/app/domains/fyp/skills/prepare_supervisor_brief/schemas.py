"""
Types for the prepare_supervisor_brief skill (Release 0.13).

  Grey-facing  — SupervisorBriefInput / Output: every approved decision, passed in by the runner.
  LLM-facing   — LLMTalkingPointsDraft: only the talking points for the 10 fixed questions
                 (the readiness checks and the summary are built in plain code).
  Progress     — BriefPhase / BriefProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategy,
    DatasetOption,
    FeasibilityReport,
    FunctionalArea,
    FYPDesign,
    ModelPlan,
    ProblemSourceDetail,
    ProjectDefinition,
    SupervisorBrief,
    SupervisorQuestionId,
    TechnicalPlan,
    TechnologyPlan,
)
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief

# The likely supervisor questions (blueprint §35), in the blueprint's order.
QUESTIONS = {
    SupervisorQuestionId.WHY_THIS_PROBLEM: "Why did you choose this problem?",
    SupervisorQuestionId.EVIDENCE: "What evidence proves the problem exists?",
    SupervisorQuestionId.USERS: "Who will use the system?",
    SupervisorQuestionId.EXISTING_SOLUTIONS: "What already exists?",
    SupervisorQuestionId.CONTRIBUTION: "What is your contribution?",
    SupervisorQuestionId.WHY_AI: "Why does the project require AI?",
    SupervisorQuestionId.DATASET_SOURCE: "Where will the dataset come from?",
    SupervisorQuestionId.MODEL_EVALUATION: "How will the model be evaluated?",
    SupervisorQuestionId.LIMITATIONS: "What are the limitations?",
    SupervisorQuestionId.TIMELINE: "Is the project achievable within the FYP timeline?",
}


class SupervisorBriefInput(BaseModel):
    """Every approved decision so far."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    evidence: list[ProblemSourceDetail]          # the sources behind the chosen problem
    design: FYPDesign
    definition: ProjectDefinition
    strategy: AIStrategy
    dataset: DatasetOption
    models: ModelPlan
    technology: TechnologyPlan
    technical: TechnicalPlan
    feasibility: FeasibilityReport


class SupervisorBriefOutput(BaseModel):
    brief: SupervisorBrief
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}


class LLMQuestionDraft(BaseModel):
    id: str
    talking_points: list[str]


class LLMTalkingPointsDraft(BaseModel):
    questions: list[LLMQuestionDraft]


class BriefPhase(str, Enum):
    CHECKING = "checking_readiness"
    WRITING = "writing_talking_points"
    REVIEWING = "reviewing_brief"


class BriefProgress(BaseModel):
    phase: BriefPhase
    label: str


BriefProgressCallback = Callable[[BriefProgress], Awaitable[None]]
