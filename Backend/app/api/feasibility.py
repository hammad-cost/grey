"""
Feasibility analysis routes (Release 0.12).

  POST /projects/{id}/feasibility          — check whether the project is feasible, streaming progress
  POST /projects/{id}/feasibility/accept   — the student accepts the report (HITL resume)
  GET  /projects/{id}/feasibility          — the report and the latest attempt

Routes stay thin: the feasibility runner does the work.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import FeasibilityRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import AcceptFeasibilityRequest
from app.domains.fyp.schemas.responses import FeasibilityResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.feasibility import (
    FeasibilityNotAllowedError,
    accept_feasibility_report,
    build_feasibility_view,
    start_feasibility,
)
from app.domains.fyp.workflows.feasibility.graph import feasibility_graph as _feasibility_graph

router = APIRouter(prefix="/projects", tags=["feasibility"])

_EXPECTED_ERRORS = (ProjectNotFoundError, FeasibilityNotAllowedError, FeasibilityRunAlreadyRunningError)


def get_feasibility_graph():
    """The shared Feasibility workflow graph. A dependency, so tests can swap it."""
    return _feasibility_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


@router.post("/{workspace_id}/feasibility")
async def assess_feasibility(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_feasibility_graph),
) -> StreamingResponse:
    """Check feasibility, streaming progress. 404; 409 technical plan not approved / already checked / running."""
    session = session_factory()
    try:
        run = await start_feasibility(workspace_id, WorkspaceBrainRepository(session), graph)
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


@router.post("/{workspace_id}/feasibility/accept", response_model=GreyEvent)
async def accept_feasibility(
    workspace_id: str,
    body: AcceptFeasibilityRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_feasibility_graph),
) -> GreyEvent:
    """Accept the feasibility report. Release 0.12 ends here. 404; 409 nothing to accept / wrong id."""
    try:
        return await accept_feasibility_report(workspace_id, body.report_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/feasibility", response_model=FeasibilityResponse)
async def get_feasibility(workspace_id: str, session: AsyncSession = Depends(get_session)) -> FeasibilityResponse:
    """Return the feasibility report (once checked) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return FeasibilityResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        feasibility=build_feasibility_view(snapshot),
        latest_run=snapshot.feasibility_run,
    )
