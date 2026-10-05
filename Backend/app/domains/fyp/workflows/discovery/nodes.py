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
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import WorkflowState
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.research_evidence.schemas import (
    ResearchEvidenceInput,
    ResearchProgress,
)
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


# The name the Evidence Research skill is registered under in the SkillRegistry.
RESEARCH_SKILL_NAME = "research_evidence"

# Marks a progress update sent through LangGraph's custom stream, so the
# research runner can tell it apart from anything else on that stream.
RESEARCH_PROGRESS_KIND = "research_progress"


def make_evidence_research_node(skills: SkillRegistry):
    """
    Build the evidence_research node, bound to a SkillRegistry.

    The node only orchestrates:
      1. look up the Evidence Research skill by name in the registry,
      2. give it the industry and branch from the workflow state,
      3. forward the skill's safe progress updates to LangGraph's stream,
      4. put the skill's result into the workflow state.

    All research logic lives in the skill. The node never creates the skill,
    and never saves anything — the research runner saves the result to the
    Project Brain.

    If the skill fails, the error propagates and the graph stays paused before
    this node, so running the graph again retries the research.
    """

    async def evidence_research_node(state: DiscoveryState) -> dict:
        skill = skills.get(RESEARCH_SKILL_NAME)
        write = get_stream_writer()

        async def forward_progress(progress: ResearchProgress) -> None:
            write({"kind": RESEARCH_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

        output = await skill.execute(
            ResearchEvidenceInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
            ),
            on_progress=forward_progress,
        )

        return {
            "research_output": output.model_dump(mode="json"),
            "workflow_state": WorkflowState.EVIDENCE_RESEARCH.value,
        }

    return evidence_research_node
