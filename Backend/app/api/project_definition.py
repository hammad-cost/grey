"""
Project definition and scope API routes (Release 0.6).

  POST /projects/{id}/project-definition  — write the definition, streaming progress
  POST /projects/{id}/scope/move          — move one feature between core / optional / out of scope
  POST /projects/{id}/scope/approve       — the student approves the scope (HITL resume)
  GET  /projects/{id}/project-definition  — the definition, scope and latest attempt

Rules (same as the other routes):
  - Routes stay thin. The project definition runner does the work; routes only
    translate its errors into HTTP status codes and send its events.
  - Routes never call the LLM. Only the skill does, through the LLM gateway,
    inside the Project Definition workflow.

Streaming format: one GreyEvent per line as JSON (application/x-ndjson),
exactly like the other streams. The streaming route opens its own database
session, because the definition is saved at the end of the stream.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import ProjectDefinitionRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.scope_rules import ScopeChangeError
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ApproveScopeRequest, MoveScopeItemRequest
from app.domains.fyp.schemas.responses import ProjectDefinitionResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.project_definition import (
    ProjectDefinitionNotAllowedError,
    approve_scope,
    build_definition_view,
    move_scope,
    start_project_definition,
)
from app.domains.fyp.workflows.project_definition.graph import (
    project_definition_graph as _project_definition_graph,
)

router = APIRouter(prefix="/projects", tags=["project_definition"])

_EXPECTED_ERRORS = (
    ProjectNotFoundError,
    ProjectDefinitionNotAllowedError,
    ProjectDefinitionRunAlreadyRunningError,
    ScopeChangeError,
)


def get_project_definition_graph():
    """The shared Project Definition workflow graph. A dependency, so tests can swap it."""
    return _project_definition_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


@router.post("/{workspace_id}/project-definition")
async def define_project(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_project_definition_graph),
) -> StreamingResponse:
    """
    Write the problem definition, scope and proposed solution, streaming progress.

      404 — project not found
      409 — the FYP isn't approved yet, the project is already defined, or it is being defined

    Once streaming has started the status is always 200; a failure is sent as a
    final `project_definition_failed` event instead.
    """
    session = session_factory()
    try:
        definition_session = await start_project_definition(workspace_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        await session.close()
        raise _http_error(error) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in definition_session.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.post("/{workspace_id}/scope/move", response_model=GreyEvent)
async def move_scope_item(
    workspace_id: str,
    body: MoveScopeItemRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_project_definition_graph),
) -> GreyEvent:
    """
    Move one feature to core, optional or out of scope.

      404 — project not found
      409 — no scope to review, or the move breaks a scope rule (e.g. too few core features)
      422 — not one of the three lists
    """
    try:
        return await move_scope(workspace_id, body.item_id, body.to, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.post("/{workspace_id}/scope/approve", response_model=GreyEvent)
async def approve_project_scope(
    workspace_id: str,
    body: ApproveScopeRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_project_definition_graph),
) -> GreyEvent:
    """
    Approve the scope. Release 0.6 ends here.

      404 — project not found
      409 — no scope to approve, or not this project's definition
    """
    try:
        return await approve_scope(workspace_id, body.definition_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/project-definition", response_model=ProjectDefinitionResponse)
async def get_project_definition(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProjectDefinitionResponse:
    """Return the definition with its scope (once written) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return ProjectDefinitionResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        definition=build_definition_view(snapshot),
        latest_run=snapshot.project_definition_run,
    )
