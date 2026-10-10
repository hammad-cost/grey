"""
Supervisor readiness routes (Release 0.13).

  POST /projects/{id}/supervisor-brief           — readiness checks, summary and likely questions, streaming progress
  POST /projects/{id}/supervisor-brief/confirm   — the student confirms they're ready (HITL resume)
  GET  /projects/{id}/supervisor-brief           — the brief and the latest attempt

Routes stay thin: the supervisor readiness runner does the work.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import ReadinessRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ConfirmSupervisorReadyRequest
from app.domains.fyp.schemas.responses import SupervisorBriefResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.supervisor_readiness import (
    ReadinessNotAllowedError,
    build_supervisor_brief_view,
    confirm_supervisor_ready,
    start_supervisor_brief,
)
from app.domains.fyp.workflows.supervisor_readiness.graph import (
    supervisor_readiness_graph as _supervisor_readiness_graph,
)

router = APIRouter(prefix="/projects", tags=["supervisor"])

_EXPECTED_ERRORS = (ProjectNotFoundError, ReadinessNotAllowedError, ReadinessRunAlreadyRunningError)


def get_supervisor_readiness_graph():
    """The shared Supervisor Readiness workflow graph. A dependency, so tests can swap it."""
    return _supervisor_readiness_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


@router.post("/{workspace_id}/supervisor-brief")
async def prepare_supervisor_brief(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_supervisor_readiness_graph),
) -> StreamingResponse:
    """Prepare the supervisor brief, streaming progress. 404; 409 feasibility not accepted / already prepared / running."""
    session = session_factory()
    try:
        run = await start_supervisor_brief(workspace_id, WorkspaceBrainRepository(session), graph)
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


@router.post("/{workspace_id}/supervisor-brief/confirm", response_model=GreyEvent)
async def confirm_ready(
    workspace_id: str,
    body: ConfirmSupervisorReadyRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_supervisor_readiness_graph),
) -> GreyEvent:
    """Confirm the student is ready. Release 0.13 ends here. 404; 409 nothing to confirm / wrong id."""
    try:
        return await confirm_supervisor_ready(workspace_id, body.brief_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/supervisor-brief", response_model=SupervisorBriefResponse)
async def get_supervisor_brief(workspace_id: str, session: AsyncSession = Depends(get_session)) -> SupervisorBriefResponse:
    """Return the supervisor brief (once prepared) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return SupervisorBriefResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        supervisor_brief=build_supervisor_brief_view(snapshot),
        latest_run=snapshot.readiness_run,
    )
