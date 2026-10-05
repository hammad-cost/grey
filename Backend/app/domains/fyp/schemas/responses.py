"""
Response body schemas for FYP API routes (other than GreyEvent).

These define the shape of what the backend sends back to the frontend.
"""
from pydantic import BaseModel

from app.core.brain.schemas import ResearchRun, StoredEvidenceSource


class EvidenceListResponse(BaseModel):
    """Body for GET /projects/{workspace_id}/evidence."""
    workspace_id: str
    research: ResearchRun | None = None       # latest research attempt, None if never run
    evidence: list[StoredEvidenceSource] = []  # strongest first (Tier A → C)
