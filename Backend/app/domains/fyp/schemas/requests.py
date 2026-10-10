"""
Request body schemas for FYP API routes.

These define the shape of what the frontend sends to the backend.
FastAPI validates incoming JSON against these automatically — if the
request body is wrong, FastAPI returns a 422 error before the route runs.
"""
from pydantic import BaseModel, Field

from app.core.brain.schemas import (
    AIStrategyPreference,
    ArchitecturePreference,
    DatasetChoice,
    DatasetPreference,
    FYPAdjustment,
    ModelPreference,
    ScopeKind,
    TechnologyPreference,
)
from app.domains.fyp.skills.design_fyp.schemas import MAX_NOTE_CHARS


class SelectIndustryRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/industry."""
    industry: str


class SelectBranchRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/branch."""
    branch: str


class SelectProblemRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/problem — the id of one of the problem options."""
    problem_id: str = Field(min_length=1)


class AdjustFYPRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/fyp-design/adjust — one controlled redesign."""
    adjustment: FYPAdjustment
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)   # optional, short


class ApproveFYPRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/fyp-design/approve — the id of the current draft."""
    design_id: str = Field(min_length=1)


class MoveScopeItemRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/scope/move — one feature and the list it goes to."""
    item_id: str = Field(min_length=1)
    to: ScopeKind                          # "core", "optional" or "out_of_scope"


class ApproveScopeRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/scope/approve — the id of the project definition."""
    definition_id: str = Field(min_length=1)


class RecheckAIStrategyRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/ai-strategy/recheck — what the student wants Grey to consider."""
    preference: AIStrategyPreference       # "without_ai" or "existing_model"


class ApproveAIStrategyRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/ai-strategy/approve — the id of the AI strategy."""
    strategy_id: str = Field(min_length=1)


class ResearchDatasetsRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/datasets/research — how the student wants Grey to search again."""
    preference: DatasetPreference          # "other_options" or "own_data"


class SelectDatasetRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/datasets/select — the recommendation's id and which dataset."""
    plan_id: str = Field(min_length=1)
    choice: DatasetChoice                  # "primary" or "alternative"


class ResearchModelsRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/models/research."""
    preference: ModelPreference            # "other_options"


class ApproveModelsRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/models/approve — the id of the model plan."""
    plan_id: str = Field(min_length=1)


class ReplanTechnologyRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/technology/replan."""
    preference: TechnologyPreference       # "simpler"


class ApproveTechnologyRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/technology/approve — the id of the technology plan."""
    plan_id: str = Field(min_length=1)


class RedesignArchitectureRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/architecture/redesign."""
    preference: ArchitecturePreference     # "simpler"


class ApproveTechnicalPlanRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/architecture/approve — the id of the technical plan."""
    plan_id: str = Field(min_length=1)


class AcceptFeasibilityRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/feasibility/accept — the id of the feasibility report."""
    report_id: str = Field(min_length=1)


class ConfirmSupervisorReadyRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/supervisor-brief/confirm — the id of the supervisor brief."""
    brief_id: str = Field(min_length=1)
