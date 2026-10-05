"""
Request body schemas for FYP API routes.

These define the shape of what the frontend sends to the backend.
FastAPI validates incoming JSON against these automatically — if the
request body is wrong, FastAPI returns a 422 error before the route runs.
"""
from pydantic import BaseModel


class SelectIndustryRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/industry."""
    industry: str


class SelectBranchRequest(BaseModel):
    """Body for POST /projects/{workspace_id}/branch."""
    branch: str
