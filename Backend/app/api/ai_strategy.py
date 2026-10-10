"""
AI necessity check and AI strategy API routes (Release 0.7).

  POST /projects/{id}/ai-strategy           — check whether the project needs AI, streaming progress
  POST /projects/{id}/ai-strategy/recheck   — check again with the student's preference, streaming progress
  POST /projects/{id}/ai-strategy/approve   — the student approves the AI strategy (HITL resume)
  GET  /projects/{id}/ai-strategy           — the strategy and the latest attempt

Rules (same as the other routes):
  - Routes stay thin. The AI strategy runner does the work; routes only
    translate its errors into HTTP status codes and send its events.
  - Routes never call the LLM. Only the skill does, through the LLM gateway,
    inside the AI Strategy workflow.

Streaming format: one GreyEvent per line as JSON (application/x-ndjson),
exactly like the other streams. The streaming routes open their own database
session, because the strategy is saved at the end of the stream.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import AIStrategyRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import ApproveAIStrategyRequest, RecheckAIStrategyRequest
from app.domains.fyp.schemas.responses import AIStrategyResponse
from app.domains.fyp.workflows.ai_strategy import (
    AIStrategyNotAllowedError,
    approve_strategy,
    build_ai_strategy_view,
    start_ai_recheck,
    start_ai_strategy,
)
from app.domains.fyp.workflows.ai_strategy.graph import ai_strategy_graph as _ai_strategy_graph
from app.domains.fyp.workflows.discovery import ProjectNotFoundError

router = APIRouter(prefix="/projects", tags=["ai_strategy"])

_EXPECTED_ERRORS = (ProjectNotFoundError, AIStrategyNotAllowedError, AIStrategyRunAlreadyRunningError)


def get_ai_strategy_graph():
    """The shared AI Strategy workflow graph. A dependency, so tests can swap it."""
    return _ai_strategy_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


async def _stream(start, session_factory) -> StreamingResponse:
    """
    Start a check with its own database session (`start` takes the repository),
    then stream its events. Expected problems become 404 / 409 before streaming.
    """
    session = session_factory()
    try:
        check = await start(WorkspaceBrainRepository(session))
    except _EXPECTED_ERRORS as error:
        await session.close()
        raise _http_error(error) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in check.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.post("/{workspace_id}/ai-strategy")
async def check_ai_need(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_ai_strategy_graph),
) -> StreamingResponse:
    """
    Check whether the project needs AI and plan the AI strategy, streaming progress.

      404 — project not found
      409 — the scope isn't approved yet, the AI need is already checked, or a check is running

    Once streaming has started the status is always 200; a failure is sent as a
    final `ai_strategy_failed` event instead.
    """
    return await _stream(lambda repo: start_ai_strategy(workspace_id, repo, graph), session_factory)


@router.post("/{workspace_id}/ai-strategy/recheck")
async def recheck_ai_strategy(
    workspace_id: str,
    body: RecheckAIStrategyRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_ai_strategy_graph),
) -> StreamingResponse:
    """
    Check again with the student's preference (up to 2 times), streaming progress.

      404 — project not found
      409 — no strategy to review, no re-checks left, the preference makes no sense
            for this strategy (e.g. "without AI" when it already needs none), or a check is running
      422 — not one of the preferences
    """
    return await _stream(
        lambda repo: start_ai_recheck(workspace_id, body.preference, repo, graph), session_factory
    )


@router.post("/{workspace_id}/ai-strategy/approve", response_model=GreyEvent)
async def approve_ai_strategy(
    workspace_id: str,
    body: ApproveAIStrategyRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_ai_strategy_graph),
) -> GreyEvent:
    """
    Approve the AI strategy. Release 0.7 ends here.

      404 — project not found
      409 — no strategy to approve, not this project's strategy, or a re-check is running
    """
    try:
        return await approve_strategy(workspace_id, body.strategy_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/ai-strategy", response_model=AIStrategyResponse)
async def get_ai_strategy(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> AIStrategyResponse:
    """Return the AI strategy (once checked) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return AIStrategyResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        ai_strategy=build_ai_strategy_view(snapshot),
        latest_run=snapshot.ai_strategy_run,
    )
