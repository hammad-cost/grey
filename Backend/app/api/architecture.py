"""
System architecture and evaluation plan routes (Release 0.11).

  POST /projects/{id}/architecture            — design the architecture + evaluation plan, streaming progress
  POST /projects/{id}/architecture/redesign   — make it simpler, streaming progress
  POST /projects/{id}/architecture/approve    — the student approves the technical plan (HITL resume)
  GET  /projects/{id}/architecture            — the plan and the latest attempt

Routes stay thin: the technical plan runner does the work.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import ArchitectureRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ApproveTechnicalPlanRequest, RedesignArchitectureRequest
from app.domains.fyp.schemas.responses import TechnicalPlanResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.technical_plan import (
    ArchitectureNotAllowedError,
    approve_technical_plan,
    build_technical_plan_view,
    start_architecture_redesign,
    start_technical_plan,
)
from app.domains.fyp.workflows.technical_plan.graph import technical_plan_graph as _technical_plan_graph

router = APIRouter(prefix="/projects", tags=["architecture"])

_EXPECTED_ERRORS = (ProjectNotFoundError, ArchitectureNotAllowedError, ArchitectureRunAlreadyRunningError)


def get_technical_plan_graph():
    """The shared Technical Plan workflow graph. A dependency, so tests can swap it."""
    return _technical_plan_graph


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


@router.post("/{workspace_id}/architecture")
async def design_architecture(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_technical_plan_graph),
) -> StreamingResponse:
    """Design the architecture and evaluation plan. 404; 409 technology not approved / already designed / running."""
    return await _stream(lambda repo: start_technical_plan(workspace_id, repo, graph), session_factory)


@router.post("/{workspace_id}/architecture/redesign")
async def redesign_architecture(
    workspace_id: str,
    body: RedesignArchitectureRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_technical_plan_graph),
) -> StreamingResponse:
    """Make the architecture simpler (up to 2 times). 404; 409 nothing to review / none left / running; 422."""
    return await _stream(
        lambda repo: start_architecture_redesign(workspace_id, body.preference, repo, graph), session_factory
    )


@router.post("/{workspace_id}/architecture/approve", response_model=GreyEvent)
async def approve_architecture(
    workspace_id: str,
    body: ApproveTechnicalPlanRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_technical_plan_graph),
) -> GreyEvent:
    """Approve the architecture and evaluation plan. Release 0.11 ends here. 404; 409."""
    try:
        return await approve_technical_plan(workspace_id, body.plan_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/architecture", response_model=TechnicalPlanResponse)
async def get_architecture(workspace_id: str, session: AsyncSession = Depends(get_session)) -> TechnicalPlanResponse:
    """Return the technical plan (once designed) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return TechnicalPlanResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        technical_plan=build_technical_plan_view(snapshot),
        latest_run=snapshot.architecture_run,
    )
