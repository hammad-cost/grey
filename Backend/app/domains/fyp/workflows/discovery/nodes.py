"""
Discovery workflow nodes.

Each function here is one step in the Discovery workflow graph.
Nodes receive the current LangGraph state and return a dict of updates.

Rules:
  - Nodes do not call the database directly — the API layer does that.
  - Nodes do not decide what the frontend shows — the event system does that.
  - Nodes validate decisions and control state transitions.
  - Nodes pause at mandatory HITL points using interrupt().
"""
from langgraph.types import interrupt

from app.core.brain.schemas import WorkflowState
from app.domains.fyp.workflows.discovery.state import DiscoveryState
from app.domains.fyp.workflows.discovery.taxonomy import (
    INDUSTRIES,
    get_branches_for_industry,
    is_valid_branch,
    is_valid_industry,
)


def industry_selection_node(state: DiscoveryState) -> dict:
    """
    Pause and wait for the student to select an industry.

    The interrupt payload tells the API layer what options are available.
    When the student selects an industry, the API resumes the graph
    with Command(resume="Defense") (or whichever industry was chosen).

    This is a mandatory HITL interrupt — the workflow cannot proceed
    without an explicit industry selection.
    """
    selected = interrupt({
        "stage": WorkflowState.INDUSTRY_SELECTION.value,
        "available_industries": INDUSTRIES,
        "prompt": "Which industry do you want to build your FYP for?",
    })

    if not is_valid_industry(selected):
        raise ValueError(
            f"'{selected}' is not a valid industry. "
            f"Valid options: {INDUSTRIES}"
        )

    return {
        "industry": selected,
        "workflow_state": WorkflowState.BRANCH_SELECTION.value,
    }


def branch_selection_node(state: DiscoveryState) -> dict:
    """
    Pause and wait for the student to select a branch within their chosen industry.

    The interrupt payload includes the branches that are relevant to the
    already-selected industry. The workflow knows the industry because
    industry_selection_node ran and committed its state before this node starts.

    This is a mandatory HITL interrupt.
    """
    industry = state["industry"]
    branches = get_branches_for_industry(industry)

    selected = interrupt({
        "stage": WorkflowState.BRANCH_SELECTION.value,
        "industry": industry,
        "available_branches": branches,
        "prompt": f"Which branch of {industry} do you want to focus on?",
    })

    if not is_valid_branch(industry, selected):
        raise ValueError(
            f"'{selected}' is not a valid branch for '{industry}'. "
            f"Valid options: {branches}"
        )

    return {
        "branch": selected,
        "workflow_state": WorkflowState.EVIDENCE_RESEARCH.value,
    }


def evidence_research_node(state: DiscoveryState) -> dict:
    """
    Mark the project as having entered EVIDENCE_RESEARCH and stop.

    Release 0.1: this node does nothing except confirm the transition.
    Real evidence research (ResearchEvidenceSkill) is added in a future slice.
    """
    return {
        "workflow_state": WorkflowState.EVIDENCE_RESEARCH.value,
    }
