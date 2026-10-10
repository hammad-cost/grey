"""
Types for the find_datasets skill (Release 0.8).

  LLM-facing   — LLMDatasetPlanDraft: the shape the model must return.
                 Not trusted until validation.py has checked it. The model
                 picks a public dataset by its candidate NUMBER, never by
                 writing a link, so it can't invent one.
  Grey-facing  — FindDatasetsInput / Output: what the workflow sends and gets back.
  Progress     — DatasetPhase / DatasetProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategy,
    DatasetCandidate,
    DatasetPlan,
    DatasetPreference,
    FunctionalArea,
    ProjectDefinition,
)
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief


class FindDatasetsInput(BaseModel):
    """What the skill needs: the student's decisions so far, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    definition: ProjectDefinition                     # the approved definition and scope
    strategy: AIStrategy                              # the approved AI strategy
    preference: DatasetPreference | None = None       # set for a re-search
    previous_plan: DatasetPlan | None = None          # the recommendation being replaced
    known_candidates: list[DatasetCandidate] = []     # pages the last search found (reused by a re-search)


class FindDatasetsOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    plan: DatasetPlan
    candidates: list[DatasetCandidate]         # every page the model could choose from
    searches_used: int
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}     # why earlier replies were rejected, if any


class DatasetsUnavailableError(Exception):
    """Every search failed, so Grey has no pages to choose from. Nothing is saved; the student can retry."""

    def __init__(self, message: str, searches_used: int) -> None:
        super().__init__(message)
        self.searches_used = searches_used


# ── What the model returns ────────────────────────────────────────────────────

class LLMDatasetOptionDraft(BaseModel):
    kind: str                     # public | synthetic | student_collected
    candidate_number: int         # the page's number for a public dataset; 0 for own data
    name: str
    size: str
    main_features: list[str]
    labels: str
    license: str
    relevance: str
    preprocessing: list[str]
    limitations: list[str]
    fit: str                      # good | partial
    how_to_get: str               # own data only; "" for a public dataset


class LLMDatasetPlanDraft(BaseModel):
    """The whole reply the model must return. Choices and facts are checked by validation.py."""
    purpose: str
    primary: LLMDatasetOptionDraft
    alternative: LLMDatasetOptionDraft


# ── Progress ──────────────────────────────────────────────────────────────────

class DatasetPhase(str, Enum):
    """What Grey is doing while it looks for datasets. Safe activity only."""
    SEARCHING = "searching_datasets"
    CHOOSING = "choosing_datasets"
    CHECKING = "checking_datasets"


class DatasetProgress(BaseModel):
    phase: DatasetPhase
    label: str


DatasetProgressCallback = Callable[[DatasetProgress], Awaitable[None]]
