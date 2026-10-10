"""
Grey event envelope.

Every response from the backend to the frontend uses this shape.
The frontend reads `type`, `stage`, `status`, and `allowed_actions`
to decide which UI component to show and which buttons to enable.

This envelope is the stable contract between backend and frontend —
it must not change shape even as the backend evolves internally.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel


class EventType(str, Enum):
    """
    All named events the backend can emit.
    Release 0.1 uses the first four; Release 0.2 adds the research events.
    The rest are defined now so the frontend contract is stable from the start.
    """
    # Release 0.1
    PROJECT_CREATED = "project_created"
    STAGE_CHANGED = "stage_changed"
    INDUSTRY_SAVED = "industry_saved"
    BRANCH_SAVED = "branch_saved"

    # Release 0.2 — evidence research, in the order the student sees them.
    # These only describe safe activity (what Grey is doing), never reasoning.
    RESEARCH_STARTED = "research_started"
    SEARCHING_SOURCES = "searching_sources"
    SOURCES_FOUND = "sources_found"
    EVALUATING_EVIDENCE = "evaluating_evidence"
    STORING_EVIDENCE = "storing_evidence"
    RESEARCH_COMPLETED = "research_completed"
    RESEARCH_FAILED = "research_failed"

    # Release 0.3 — problem opportunities. Safe activity only, never reasoning.
    PROBLEM_EXTRACTION_STARTED = "problem_extraction_started"
    PROBLEM_EXTRACTION_PROGRESS = "problem_extraction_progress"
    PROBLEM_OPTIONS_READY = "problem_options_ready"
    PROBLEM_EXTRACTION_FAILED = "problem_extraction_failed"
    PROBLEM_SELECTED = "problem_selected"

    # Release 0.5 — from problem to FYP. Safe activity only, never reasoning.
    FYP_DESIGN_STARTED = "fyp_design_started"
    FYP_DESIGN_PROGRESS = "fyp_design_progress"
    AREA_CLASSIFIED = "area_classified"
    FYP_DIRECTION_READY = "fyp_direction_ready"
    FYP_DESIGN_FAILED = "fyp_design_failed"
    FYP_DIRECTION_APPROVED = "fyp_direction_approved"

    # Release 0.6 — project definition and scope. Safe activity only, never reasoning.
    PROJECT_DEFINITION_STARTED = "project_definition_started"
    PROJECT_DEFINITION_PROGRESS = "project_definition_progress"
    PROJECT_DEFINITION_READY = "project_definition_ready"
    PROJECT_DEFINITION_FAILED = "project_definition_failed"
    SCOPE_UPDATED = "scope_updated"
    SCOPE_APPROVED = "scope_approved"

    # Release 0.7 — AI necessity check and AI strategy. Safe activity only, never reasoning.
    AI_STRATEGY_STARTED = "ai_strategy_started"
    AI_STRATEGY_PROGRESS = "ai_strategy_progress"
    AI_STRATEGY_READY = "ai_strategy_ready"
    AI_STRATEGY_FAILED = "ai_strategy_failed"
    AI_STRATEGY_APPROVED = "ai_strategy_approved"

    # Future — defined here so event names are never magic strings
    HUMAN_INPUT_REQUIRED = "human_input_required"
    DATASET_OPTIONS_READY = "dataset_options_ready"
    ARCHITECTURE_READY = "architecture_ready"
    FEASIBILITY_READY = "feasibility_ready"
    SUPERVISOR_READINESS_READY = "supervisor_readiness_ready"
    PROPOSAL_READY = "proposal_ready"
    BRAIN_UPDATED = "brain_updated"
    CHANGE_IMPACT_READY = "change_impact_ready"
    ERROR = "error"


class EventStatus(str, Enum):
    """
    What the workflow is doing right now.
    The frontend uses this to show spinners, enable buttons, or lock the UI.
    """
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_USER = "awaiting_user"   # Grey is paused, waiting for the student to act
    BLOCKED = "blocked"
    COMPLETE = "complete"


class AllowedAction(str, Enum):
    """
    Actions the frontend is permitted to call at a given moment.
    The backend includes only the currently valid actions in each event.
    This prevents the student from skipping steps.
    """
    START_PROJECT = "startProject"
    SELECT_INDUSTRY = "selectIndustry"
    SELECT_BRANCH = "selectBranch"
    START_RESEARCH = "startResearch"       # run (or retry) evidence research
    EXTRACT_PROBLEMS = "extractProblems"   # find (or retry finding) problem options from the evidence
    SELECT_PROBLEM = "selectProblem"
    REQUEST_MORE_PROBLEMS = "requestMoreProblems"
    DESIGN_FYP = "designFYP"                       # turn the chosen problem into an FYP (or retry)
    APPROVE_FYP_DIRECTION = "approveFYPDirection"
    ADJUST_FYP_DIRECTION = "adjustFYPDirection"    # one controlled redesign (up to 3)
    DEFINE_PROJECT = "defineProject"               # write the problem definition, scope and solution (or retry)
    MODIFY_SCOPE = "modifyScope"                   # move a feature between core / optional / out of scope
    APPROVE_SCOPE = "approveScope"
    CHECK_AI_NEED = "checkAINeed"                  # check whether the project needs AI, and plan it (or retry)
    RECHECK_AI_STRATEGY = "recheckAIStrategy"      # check again with a preference (up to 2 times)
    APPROVE_AI_STRATEGY = "approveAIStrategy"
    SELECT_DATASET = "selectDataset"
    REQUEST_DATASET_ALTERNATIVE = "requestDatasetAlternative"
    APPROVE_TECHNICAL_PLAN = "approveTechnicalPlan"
    GO_BACK = "goBack"
    ASK_GREY = "askGrey"
    GENERATE_PROPOSAL = "generateProposal"


class GreyEvent(BaseModel):
    """
    The envelope that wraps every backend-to-frontend message.

    Example:
        {
            "type": "industry_saved",
            "workspace_id": "ws-abc",
            "domain": "fyp",
            "workflow": "discovery",
            "stage": "BRANCH_SELECTION",
            "status": "awaiting_user",
            "data": {"industry": "Defense"},
            "brain_patch": {"industry": "Defense", "industry_status": "approved"},
            "allowed_actions": ["selectBranch", "askGrey"]
        }
    """
    type: EventType
    workspace_id: str
    domain: str = "fyp"
    workflow: str
    stage: str                              # current WorkflowState value
    status: EventStatus
    data: dict[str, Any] = {}              # event-specific payload
    brain_patch: dict[str, Any] = {}       # Project Brain fields that just changed
    allowed_actions: list[AllowedAction] = []


def build_event(
    *,
    type: EventType,
    workspace_id: str,
    workflow: str,
    stage: str,
    status: EventStatus,
    data: dict[str, Any] | None = None,
    brain_patch: dict[str, Any] | None = None,
    allowed_actions: list[AllowedAction] | None = None,
    domain: str = "fyp",
) -> GreyEvent:
    """
    Convenience function for constructing a GreyEvent.
    Avoids repeating default values at every call site.
    """
    return GreyEvent(
        type=type,
        workspace_id=workspace_id,
        domain=domain,
        workflow=workflow,
        stage=stage,
        status=status,
        data=data or {},
        brain_patch=brain_patch or {},
        allowed_actions=allowed_actions or [],
    )
