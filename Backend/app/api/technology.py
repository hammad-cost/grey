"""
Technology stack and hardware routes (Release 0.10).

  POST /projects/{id}/technology           — plan the stack and hardware, streaming progress
  POST /projects/{id}/technology/replan    — make it simpler / cheaper, streaming progress
  POST /projects/{id}/technology/approve   — the student approves the plan (HITL resume)
  GET  /projects/{id}/technology           — the plan and the latest attempt

Routes stay thin: the technology runner does the work.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import TechnologyRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ApproveTechnologyRequest, ReplanTechnologyRequest
from app.domains.fyp.schemas.responses import TechnologyResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.technology_plan import (
    TechnologyNotAllowedError,
    approve_technology,
    build_technology_view,
    start_technology_plan,
    start_technology_replan,
)
from app.domains.fyp.workflows.technology_plan.graph import technology_graph as _technology_graph

router = APIRouter(prefix="/projects", tags=["technology"])

_EXPECTED_ERRORS = (ProjectNotFoundError, TechnologyNotAllowedError, TechnologyRunAlreadyRunningError)


def get_technology_graph():
    """The shared Technology Plan workflow graph. A dependency, so tests can swap it."""
    return _technology_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


async def _stream(start, session_factory) -> StreamingResponse:
    session = session_factory()
    try:
        run = await start(WorkspaceBrainRepository(session))
    except _EXPECTED_ERRORS as error:
        await session.close()
        raise _http_error(error) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in run.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.post("/{workspace_id}/technology")
async def plan_technology(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_technology_graph),
) -> StreamingResponse:
    """Plan the stack and hardware. 404 unknown project; 409 model plan not approved / already planned / running."""
    return await _stream(lambda repo: start_technology_plan(workspace_id, repo, graph), session_factory)


@router.post("/{workspace_id}/technology/replan")
async def replan_technology(
    workspace_id: str,
    body: ReplanTechnologyRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_technology_graph),
) -> StreamingResponse:
    """Make the plan simpler (up to 2 times). 404; 409 nothing to review / none left / running; 422 unknown preference."""
    return await _stream(
        lambda repo: start_technology_replan(workspace_id, body.preference, repo, graph), session_factory
    )


@router.post("/{workspace_id}/technology/approve", response_model=GreyEvent)
async def approve_technology_plan(
    workspace_id: str,
    body: ApproveTechnologyRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_technology_graph),
) -> GreyEvent:
    """Approve the technology plan. Release 0.10 ends here. 404; 409 nothing to approve / wrong id / running."""
    try:
        return await approve_technology(workspace_id, body.plan_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/technology", response_model=TechnologyResponse)
async def get_technology(workspace_id: str, session: AsyncSession = Depends(get_session)) -> TechnologyResponse:
    """Return the technology plan (once planned) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return TechnologyResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        technology=build_technology_view(snapshot),
        latest_run=snapshot.technology_run,
    )
