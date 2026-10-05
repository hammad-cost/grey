"""
Projects API routes.

These are the four discovery endpoints (research routes live in research.py).
Rules:
  - Routes stay thin. No business logic lives here.
  - Routes call the WorkspaceBrainRepository (persistence) and the
    Discovery workflow graph (state transitions). That is all.
  - Every response is a GreyEvent so the frontend has a consistent shape.
  - The discovery graph is injected as a dependency so tests can swap it
    for a fresh in-memory instance without affecting the production graph.
"""
from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brain.database import get_session
from app.core.brain.repository import WorkspaceBrainRepository
from app.core.brain.schemas import WorkflowState, WorkspaceBrainSnapshot
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.schemas.requests import SelectBranchRequest, SelectIndustryRequest
from app.domains.fyp.workflows.discovery.graph import discovery_graph as _discovery_graph
from app.domains.fyp.workflows.discovery.taxonomy import (
    INDUSTRIES,
    get_branches_for_industry,
    is_valid_branch,
    is_valid_industry,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# ── Dependency ────────────────────────────────────────────────────────────────

def get_discovery_graph():
    """
    Return the shared Discovery workflow graph.
    Defined as a dependency so tests can replace it with a fresh
    in-memory instance via app.dependency_overrides.
    """
    return _discovery_graph


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=GreyEvent, status_code=201)
async def create_project(
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_discovery_graph),
) -> GreyEvent:
    """
    Start a new FYP project.

    1. Creates a Project Brain entry in the database.
    2. Starts the Discovery workflow — it immediately pauses waiting
       for the student to pick an industry.
    3. Returns a GreyEvent telling the frontend to show the IndustrySelector.
    """
    # 1. Create the persistent project record
    repo = WorkspaceBrainRepository(session)
    snapshot = await repo.create_workspace()
    workspace_id = snapshot.workspace_id

    # 2. Start the LangGraph workflow (pauses at industry_selection interrupt)
    config = {"configurable": {"thread_id": workspace_id}}
    await graph.ainvoke(
        {
            "workspace_id": workspace_id,
            "workflow_state": WorkflowState.INDUSTRY_SELECTION.value,
            "industry": None,
            "branch": None,
        },
        config=config,
    )

    # 3. Respond with event
    return build_event(
        type=EventType.PROJECT_CREATED,
        workspace_id=workspace_id,
        workflow="discovery",
        stage=WorkflowState.INDUSTRY_SELECTION.value,
        status=EventStatus.AWAITING_USER,
        data={"available_industries": INDUSTRIES},
        brain_patch={"workflow_state": WorkflowState.INDUSTRY_SELECTION.value},
        allowed_actions=[AllowedAction.SELECT_INDUSTRY, AllowedAction.ASK_GREY],
    )


@router.post("/{workspace_id}/industry", response_model=GreyEvent)
async def select_industry(
    workspace_id: str,
    body: SelectIndustryRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_discovery_graph),
) -> GreyEvent:
    """
    Save the student's industry choice.

    1. Validates the industry against the taxonomy.
    2. Confirms the project exists.
    3. Resumes the workflow — graph validates the choice, transitions to
       BRANCH_SELECTION, then pauses waiting for a branch.
    4. Persists the decision to the Project Brain.
    5. Returns a GreyEvent telling the frontend to show the BranchSelector.
    """
    # 1. Validate industry
    if not is_valid_industry(body.industry):
        raise HTTPException(
            status_code=400,
            detail=f"'{body.industry}' is not a valid industry. "
                   f"Valid options: {INDUSTRIES}",
        )

    # 2. Confirm project exists
    repo = WorkspaceBrainRepository(session)
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{workspace_id}' not found.",
        )

    # 3. Resume workflow with the student's choice
    config = {"configurable": {"thread_id": workspace_id}}
    await graph.ainvoke(Command(resume=body.industry), config=config)

    # 4. Persist to Project Brain
    await repo.apply_decision(workspace_id, "industry", body.industry)

    # 5. Respond with event
    branches = get_branches_for_industry(body.industry)
    return build_event(
        type=EventType.INDUSTRY_SAVED,
        workspace_id=workspace_id,
        workflow="discovery",
        stage=WorkflowState.BRANCH_SELECTION.value,
        status=EventStatus.AWAITING_USER,
        data={"industry": body.industry, "available_branches": branches},
        brain_patch={"industry": body.industry, "industry_status": "approved"},
        allowed_actions=[AllowedAction.SELECT_BRANCH, AllowedAction.ASK_GREY],
    )


@router.post("/{workspace_id}/branch", response_model=GreyEvent)
async def select_branch(
    workspace_id: str,
    body: SelectBranchRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_discovery_graph),
) -> GreyEvent:
    """
    Save the student's branch choice.

    1. Confirms the project exists and an industry is already chosen.
    2. Validates the branch against the chosen industry.
    3. Resumes the workflow — graph validates the choice, transitions to
       EVIDENCE_RESEARCH, and pauses before research runs.
    4. Persists the decision and final state to the Project Brain.
    5. Returns a GreyEvent offering the startResearch action
       (research itself runs via POST /projects/{id}/research).
    """
    # 1. Confirm project exists and has an industry
    repo = WorkspaceBrainRepository(session)
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{workspace_id}' not found.",
        )
    if snapshot.industry is None:
        raise HTTPException(
            status_code=400,
            detail="An industry must be selected before choosing a branch.",
        )

    # 2. Validate branch
    if not is_valid_branch(snapshot.industry, body.branch):
        branches = get_branches_for_industry(snapshot.industry)
        raise HTTPException(
            status_code=400,
            detail=f"'{body.branch}' is not a valid branch for '{snapshot.industry}'. "
                   f"Valid options: {branches}",
        )

    # 3. Resume workflow (branch_selection → pauses before evidence_research)
    config = {"configurable": {"thread_id": workspace_id}}
    await graph.ainvoke(Command(resume=body.branch), config=config)

    # 4. Persist both decisions to Project Brain
    await repo.apply_decision(workspace_id, "branch", body.branch)
    final_snapshot = await repo.update_workflow_state(
        workspace_id, WorkflowState.EVIDENCE_RESEARCH
    )

    # 5. Respond with event — the frontend now starts research
    return build_event(
        type=EventType.BRANCH_SAVED,
        workspace_id=workspace_id,
        workflow="discovery",
        stage=WorkflowState.EVIDENCE_RESEARCH.value,
        status=EventStatus.AWAITING_USER,
        data={
            "industry": final_snapshot.industry,
            "branch": body.branch,
            "message": "Grey is ready to research evidence.",
        },
        brain_patch={
            "branch": body.branch,
            "branch_status": "approved",
            "workflow_state": WorkflowState.EVIDENCE_RESEARCH.value,
        },
        allowed_actions=[AllowedAction.START_RESEARCH],
    )


@router.get("/{workspace_id}", response_model=WorkspaceBrainSnapshot)
async def get_project(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> WorkspaceBrainSnapshot:
    """
    Read the current state of a project.

    Returns the full WorkspaceBrainSnapshot — the Project Brain contents
    for this workspace. Used by the frontend to restore state on page load.
    """
    repo = WorkspaceBrainRepository(session)
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{workspace_id}' not found.",
        )
    return snapshot
