"""
Pretrained models and APIs routes (Release 0.9).

  POST /projects/{id}/models            — look for models, APIs and code, streaming progress
  POST /projects/{id}/models/research   — look for other models, streaming progress
  POST /projects/{id}/models/approve    — the student approves the model plan (HITL resume)
  GET  /projects/{id}/models            — the plan and the latest search

Routes stay thin: the model runner does the work; routes only translate its
errors into HTTP status codes and send its events (NDJSON, like the other streams).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import ModelRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ApproveModelsRequest, ResearchModelsRequest
from app.domains.fyp.schemas.responses import ModelsResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.model_selection import (
    ModelNotAllowedError,
    approve_model_plan,
    build_model_view,
    start_model_research,
    start_model_search,
)
from app.domains.fyp.workflows.model_selection.graph import model_graph as _model_graph

router = APIRouter(prefix="/projects", tags=["models"])

_EXPECTED_ERRORS = (ProjectNotFoundError, ModelNotAllowedError, ModelRunAlreadyRunningError)


def get_model_graph():
    """The shared Model Selection workflow graph. A dependency, so tests can swap it."""
    return _model_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


async def _stream(start, session_factory) -> StreamingResponse:
    """Start a search with its own database session, then stream its events (404 / 409 before streaming)."""
    session = session_factory()
    try:
        search = await start(WorkspaceBrainRepository(session))
    except _EXPECTED_ERRORS as error:
        await session.close()
        raise _http_error(error) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in search.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.post("/{workspace_id}/models")
async def find_models(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_model_graph),
) -> StreamingResponse:
    """
    Look for pretrained models, APIs and code, streaming progress.

      404 — project not found
      409 — no dataset selected yet, models already looked for, or a search is running
    """
    return await _stream(lambda repo: start_model_search(workspace_id, repo, graph), session_factory)


@router.post("/{workspace_id}/models/research")
async def research_models(
    workspace_id: str,
    body: ResearchModelsRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_model_graph),
) -> StreamingResponse:
    """
    Look for other models (up to 2 times), streaming progress.

      404 — project not found
      409 — no plan to review, no re-searches left, the project doesn't use AI, or a search is running
      422 — not one of the preferences
    """
    return await _stream(
        lambda repo: start_model_research(workspace_id, body.preference, repo, graph), session_factory
    )


@router.post("/{workspace_id}/models/approve", response_model=GreyEvent)
async def approve_models(
    workspace_id: str,
    body: ApproveModelsRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_model_graph),
) -> GreyEvent:
    """
    Approve the model plan. Release 0.9 ends here.

      404 — project not found
      409 — no plan to approve, not this project's plan, or a re-search is running
    """
    try:
        return await approve_model_plan(workspace_id, body.plan_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/models", response_model=ModelsResponse)
async def get_models(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> ModelsResponse:
    """Return the model plan (once looked for) and the latest search."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return ModelsResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        models=build_model_view(snapshot),
        latest_run=snapshot.model_run,
    )
