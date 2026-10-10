"""
Types for the find_models skill (Release 0.9).

  LLM-facing   — LLMModelPlanDraft: the shape the model must return. It picks
                 pages by NUMBER, never by writing a link.
  Grey-facing  — FindModelsInput / Output: what the workflow sends and gets back.
  Progress     — ModelPhase / ModelProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategy,
    DatasetOption,
    FunctionalArea,
    ModelCandidate,
    ModelPlan,
    ModelPreference,
    ProjectDefinition,
)
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief


class FindModelsInput(BaseModel):
    """What the skill needs: the student's decisions so far, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    definition: ProjectDefinition                 # the approved definition and scope
    strategy: AIStrategy                          # the approved AI strategy
    dataset: DatasetOption                        # the selected dataset
    preference: ModelPreference | None = None     # set for a re-search
    previous_plan: ModelPlan | None = None        # the plan being replaced
    known_candidates: list[ModelCandidate] = []   # pages the last search found


class FindModelsOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    plan: ModelPlan
    candidates: list[ModelCandidate]
    searches_used: int
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}


class ModelsUnavailableError(Exception):
    """Every search failed, so Grey has no pages to choose from. Nothing is saved; the student can retry."""

    def __init__(self, message: str, searches_used: int) -> None:
        super().__init__(message)
        self.searches_used = searches_used


# ── What the model returns ────────────────────────────────────────────────────

class LLMModelOptionDraft(BaseModel):
    candidate_number: int        # the page's number
    kind: str                    # pretrained_model | api_service | code_repository
    name: str
    use: str                     # use_directly | fine_tune | benchmark | avoid
    reason: str
    role: str
    limitations: list[str]


class LLMModelPlanDraft(BaseModel):
    summary: str
    options: list[LLMModelOptionDraft]     # 0-3


# ── Progress ──────────────────────────────────────────────────────────────────

class ModelPhase(str, Enum):
    SEARCHING = "searching_models"
    CHOOSING = "choosing_models"
    CHECKING = "checking_models"


class ModelProgress(BaseModel):
    phase: ModelPhase
    label: str


ModelProgressCallback = Callable[[ModelProgress], Awaitable[None]]
