"""
Dataset discovery API routes (Release 0.8).

  POST /projects/{id}/datasets            — search for datasets and recommend two, streaming progress
  POST /projects/{id}/datasets/research   — search again with the student's preference, streaming progress
  POST /projects/{id}/datasets/select     — the student selects the primary or the alternative (HITL resume)
  GET  /projects/{id}/datasets            — the recommendation and the latest search

Rules (same as the other routes):
  - Routes stay thin. The dataset runner does the work; routes only
    translate its errors into HTTP status codes and send its events.
  - Routes never search or call the LLM. Only the skill does, through the
    search gateway and the LLM gateway, inside the Dataset Discovery workflow.

Streaming format: one GreyEvent per line as JSON (application/x-ndjson),
exactly like the other streams. The streaming routes open their own database
session, because the recommendation is saved at the end of the stream.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import DatasetRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ResearchDatasetsRequest, SelectDatasetRequest
from app.domains.fyp.schemas.responses import DatasetsResponse
from app.domains.fyp.workflows.dataset_discovery import (
    DatasetNotAllowedError,
    build_dataset_view,
    select_dataset_option,
    start_dataset_research,
    start_dataset_search,
)
from app.domains.fyp.workflows.dataset_discovery.graph import dataset_graph as _dataset_graph
from app.domains.fyp.workflows.discovery import ProjectNotFoundError

router = APIRouter(prefix="/projects", tags=["datasets"])

_EXPECTED_ERRORS = (ProjectNotFoundError, DatasetNotAllowedError, DatasetRunAlreadyRunningError)


def get_dataset_graph():
    """The shared Dataset Discovery workflow graph. A dependency, so tests can swap it."""
    return _dataset_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


async def _stream(start, session_factory) -> StreamingResponse:
    """
    Start a search with its own database session (`start` takes the repository),
    then stream its events. Expected problems become 404 / 409 before streaming.
    """
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


@router.post("/{workspace_id}/datasets")
async def find_datasets(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_dataset_graph),
) -> StreamingResponse:
    """
    Search for datasets and recommend a primary and an alternative, streaming progress.

      404 — project not found
      409 — the AI strategy isn't approved yet, datasets are already recommended, or a search is running

    Once streaming has started the status is always 200; a failure is sent as a
    final `dataset_search_failed` event instead.
    """
    return await _stream(lambda repo: start_dataset_search(workspace_id, repo, graph), session_factory)


@router.post("/{workspace_id}/datasets/research")
async def research_datasets(
    workspace_id: str,
    body: ResearchDatasetsRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_dataset_graph),
) -> StreamingResponse:
    """
    Search again with the student's preference (up to 2 times), streaming progress.

      404 — project not found
      409 — no datasets to review, no re-searches left, the preference makes no sense
            (e.g. "own data" when the primary already is), or a search is running
      422 — not one of the preferences
    """
    return await _stream(
        lambda repo: start_dataset_research(workspace_id, body.preference, repo, graph), session_factory
    )


@router.post("/{workspace_id}/datasets/select", response_model=GreyEvent)
async def select_dataset(
    workspace_id: str,
    body: SelectDatasetRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_dataset_graph),
) -> GreyEvent:
    """
    Select the primary or the alternative dataset. Release 0.8 ends here.

      404 — project not found
      409 — nothing to select from, not this project's recommendation, or a re-search is running
      422 — not "primary" or "alternative"
    """
    try:
        return await select_dataset_option(
            workspace_id, body.plan_id, body.choice, WorkspaceBrainRepository(session), graph
        )
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/datasets", response_model=DatasetsResponse)
async def get_datasets(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> DatasetsResponse:
    """Return the dataset recommendation (once searched) and the latest search."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return DatasetsResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        datasets=build_dataset_view(snapshot),
        latest_run=snapshot.dataset_run,
    )
