"""
Types for the design_fyp skill (Release 0.5).

  LLM-facing   — LLMFYPDesignDraft: the shape the model must return. Not trusted
                 until validation.py has checked it.
  Grey-facing  — DesignFYPInput / Output: what the workflow sends and gets back.
"""
from pydantic import BaseModel, Field, model_validator

from app.core.brain.schemas import FunctionalArea, FYPAdjustment, FYPDesign
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief

MAX_NOTE_CHARS = 200


class DesignFYPInput(BaseModel):
    """
    What the skill needs. For a redesign, `adjustment` and `previous_design`
    are both set (and an optional short `note` from the student).
    """
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    area: FunctionalArea
    problem: ProblemBrief
    adjustment: FYPAdjustment | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    previous_design: FYPDesign | None = None

    @model_validator(mode="after")
    def _redesign_needs_both(self):
        if (self.adjustment is None) != (self.previous_design is None):
            raise ValueError("A redesign needs both an adjustment and the previous design.")
        return self


class DesignFYPOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    design: FYPDesign
    provider: str
    model: str
    prompt_version: str
    rejection_summary: dict[str, int] = {}     # why earlier replies were rejected, if any


class LLMFYPDesignDraft(BaseModel):
    """The whole reply the model must return."""
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    target_user: str = Field(min_length=1)
    system_input: str = Field(min_length=1)
    system_output: str = Field(min_length=1)
    main_contribution: str = Field(min_length=1)
    scope_reduction: str = Field(min_length=1)
