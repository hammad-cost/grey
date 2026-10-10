"""
Types for the plan_ai_strategy skill (Release 0.7).

  LLM-facing   — LLMAIStrategyDraft: the shape the model must return.
                 Not trusted until validation.py has checked it. Choices are
                 plain strings ("none" when not used), because some providers'
                 strict modes handle empty values badly; the checks turn them
                 into Grey's enums.
  Grey-facing  — PlanAIStrategyInput / Output: what the workflow sends and gets back.
  Progress     — AIStrategyPhase / AIStrategyProgress: safe step labels only.
"""
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import AIStrategy, AIStrategyPreference, FunctionalArea, FYPDesign, ProjectDefinition
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief

# Written by the model when a choice does not apply (e.g. no task type without AI).
NONE = "none"


class PlanAIStrategyInput(BaseModel):
    """What the skill needs: the student's decisions so far, passed in by the runner."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    design: FYPDesign                                 # the approved FYP design
    definition: ProjectDefinition                     # the approved definition and scope
    preference: AIStrategyPreference | None = None    # set for a re-check
    previous_strategy: AIStrategy | None = None       # the answer being re-checked


class PlanAIStrategyOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    strategy: AIStrategy
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}     # why earlier replies were rejected, if any


# ── What the model returns ────────────────────────────────────────────────────

class LLMStrategyChoiceDraft(BaseModel):
    approach: str          # train_model | fine_tune | pretrained_model | use_api | hybrid | none
    reason: str


class LLMAIStrategyDraft(BaseModel):
    """The whole reply the model must return. Choices and wording are checked by validation.py."""
    necessity: str
    necessity_reason: str
    without_ai: str
    ai_component: str
    non_ai_components: list[str]
    task_type: str
    primary_strategy: LLMStrategyChoiceDraft
    fallback_strategy: LLMStrategyChoiceDraft


# ── Progress ──────────────────────────────────────────────────────────────────

class AIStrategyPhase(str, Enum):
    """What Grey is doing during the AI necessity check. Safe activity only."""
    CHECKING_AI_NEED = "checking_ai_need"
    CHECKING_ANSWER = "checking_answer"


class AIStrategyProgress(BaseModel):
    phase: AIStrategyPhase
    label: str


AIStrategyProgressCallback = Callable[[AIStrategyProgress], Awaitable[None]]
