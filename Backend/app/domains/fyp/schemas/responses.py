"""
Response body schemas for FYP API routes (other than GreyEvent).

These define the shape of what the backend sends back to the frontend.
"""
from pydantic import BaseModel

from app.core.brain.schemas import ProblemRun, ResearchRun, StoredEvidenceSource, StoredProblemCandidate


class EvidenceListResponse(BaseModel):
    """Body for GET /projects/{workspace_id}/evidence."""
    workspace_id: str
    research: ResearchRun | None = None       # latest research attempt, None if never run
    evidence: list[StoredEvidenceSource] = []  # strongest first (Tier A → C)


class ProblemListResponse(BaseModel):
    """Body for GET /projects/{workspace_id}/problems."""
    workspace_id: str
    problem_run: ProblemRun | None = None              # latest attempt, None if never run
    problems: list[StoredProblemCandidate] = []        # current options, rank 1 first, with sources
    selected_problem_id: str | None = None             # the student's choice, once made
