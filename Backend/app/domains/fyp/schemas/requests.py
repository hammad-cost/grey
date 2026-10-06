"""
Request body schemas for FYP API routes.

These define the shape of what the frontend sends to the backend.
FastAPI validates incoming JSON against these automatically — if the
request body is wrong, FastAPI returns a 422 error before the route runs.
"""
from pydantic import BaseModel, Field

from app.core.brain.schemas import FYPAdjustment
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
