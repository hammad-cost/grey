"""
Types for the define_project skill (Release 0.6).

  LLM-facing   — LLMProjectDefinitionDraft: the shape the model must return.
                 Not trusted until validation.py has checked it.
  Grey-facing  — DefineProjectInput / Output: what the workflow sends and gets back.
  Progress     — DefinitionPhase / DefinitionProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import FunctionalArea, FYPDesign, ProjectDefinition
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief


class DefineProjectInput(BaseModel):
    """What the skill needs: the student's decisions so far, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    design: FYPDesign                     # the approved FYP design


class DefineProjectOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    definition: ProjectDefinition
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}     # why earlier replies were rejected, if any


# ── What the model returns ────────────────────────────────────────────────────

class LLMProblemDefinitionDraft(BaseModel):
    problem_statement: str
    affected_users: str
    why_it_matters: str
    current_solutions: str
    gap: str
    what_will_be_built: str


class LLMModuleDraft(BaseModel):
    name: str
    purpose: str


class LLMFeatureDraft(BaseModel):
    title: str
    description: str


class LLMProjectDefinitionDraft(BaseModel):
    """The whole reply the model must return. Sizes and wording are checked by validation.py."""
    problem_definition: LLMProblemDefinitionDraft
    system_purpose: str
    modules: list[LLMModuleDraft]
    workflow_steps: list[str]
    core_features: list[LLMFeatureDraft]
    optional_features: list[LLMFeatureDraft]
    out_of_scope: list[LLMFeatureDraft]


# ── Progress ──────────────────────────────────────────────────────────────────

class DefinitionPhase(str, Enum):
    """What Grey is doing while it defines the project. Safe activity only."""
    DEFINING_PROJECT = "defining_project"
    CHECKING_DEFINITION = "checking_definition"


class DefinitionProgress(BaseModel):
    phase: DefinitionPhase
    label: str


DefinitionProgressCallback = Callable[[DefinitionProgress], Awaitable[None]]
