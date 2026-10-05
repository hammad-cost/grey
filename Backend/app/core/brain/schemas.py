"""
Pydantic schemas for the Workspace Brain.

These are the typed data shapes that the rest of the application works with.
The ORM model (models.py) talks to the database; these schemas are what
the repository returns to callers — pure Python objects, no database coupling.
"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class WorkflowState(str, Enum):
    """
    All possible stages of the FYP journey.
    Release 0.1 uses only the first three.
    The rest are defined now so the state machine can be extended later
    without changing this file.
    """
    INDUSTRY_SELECTION = "INDUSTRY_SELECTION"
    BRANCH_SELECTION = "BRANCH_SELECTION"
    EVIDENCE_RESEARCH = "EVIDENCE_RESEARCH"
    # Future states — not used in Release 0.1
    PROBLEM_OPTIONS = "PROBLEM_OPTIONS"
    PROBLEM_SELECTED = "PROBLEM_SELECTED"
    AREA_CLASSIFICATION = "AREA_CLASSIFICATION"
    FYP_DESIGN = "FYP_DESIGN"
    SCOPE = "SCOPE"
    DATASET_DISCOVERY = "DATASET_DISCOVERY"
    AI_STRATEGY = "AI_STRATEGY"
    TECHNOLOGY_PLAN = "TECHNOLOGY_PLAN"
    ARCHITECTURE = "ARCHITECTURE"
    EVALUATION = "EVALUATION"
    FEASIBILITY = "FEASIBILITY"
    SUPERVISOR_READINESS = "SUPERVISOR_READINESS"
    PROPOSAL_GENERATION = "PROPOSAL_GENERATION"
    COMPLETE = "COMPLETE"


class DecisionStatus(str, Enum):
    """
    Lifecycle of a single decision inside the Project Brain.
    A decision is not authoritative until it reaches APPROVED.
    """
    CANDIDATE = "candidate"
    RECOMMENDED = "recommended"
    SELECTED = "selected"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class WorkspaceBrainSnapshot(BaseModel):
    """
    A read-only view of the current Project Brain state.
    This is what callers receive from WorkspaceBrainRepository.get_snapshot().
    """
    workspace_id: str
    workflow_state: WorkflowState

    industry: str | None = None
    industry_status: DecisionStatus | None = None

    branch: str | None = None
    branch_status: DecisionStatus | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
