"""
FYP design API routes (Release 0.5).

  POST /projects/{id}/fyp-design          — area + first design, streaming progress
  POST /projects/{id}/fyp-design/adjust   — one controlled redesign, streaming progress
  POST /projects/{id}/fyp-design/approve  — the student approves the current draft (HITL resume)
  GET  /projects/{id}/fyp-design          — the area, current design and "Why this FYP?"

Rules (same as the other routes):
  - Routes stay thin. The FYP design runner does the work; routes only
    translate its errors into HTTP status codes and send its events.
  - Routes never call the LLM. Only the skills do, through the LLM gateway,
    inside the FYP Design workflow.

Streaming format: one GreyEvent per line as JSON (application/x-ndjson),
exactly like the research and problem streams. The streaming routes open
their own database session, because the design is saved at the end of the stream.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import FYPDesignRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import AdjustFYPRequest, ApproveFYPRequest
from app.domains.fyp.schemas.responses import FYPDesignResponse
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.fyp_design import (
    FYPDesignNotAllowedError,
    build_fyp_view,
    approve_fyp,
    start_fyp_design,
    start_fyp_redesign,
)
from app.domains.fyp.workflows.fyp_design.graph import fyp_design_graph as _fyp_design_graph

router = APIRouter(prefix="/projects", tags=["fyp_design"])


def get_fyp_design_graph():
    """The shared FYP Design workflow graph. A dependency, so tests can swap it."""
    return _fyp_design_graph


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


_EXPECTED_ERRORS = (ProjectNotFoundError, FYPDesignNotAllowedError, FYPDesignRunAlreadyRunningError)


async def _stream(session, start) -> StreamingResponse:
    """Start a design run (errors become HTTP errors), then stream its events."""
    try:
        design_session = await start()
    except _EXPECTED_ERRORS as error:
        await session.close()
        raise _http_error(error) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in design_session.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.post("/{workspace_id}/fyp-design")
async def design_fyp(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_fyp_design_graph),
) -> StreamingResponse:
    """
    Classify the chosen problem's area and design the FYP, streaming progress.

      404 — project not found
      409 — no problem chosen yet, already designed, or a design is already running

    Once streaming has started the status is always 200; a failure is sent as a
    final `fyp_design_failed` event instead.
    """
    session = session_factory()
    return await _stream(session, lambda: start_fyp_design(workspace_id, WorkspaceBrainRepository(session), graph))


@router.post("/{workspace_id}/fyp-design/adjust")
async def adjust_fyp(
    workspace_id: str,
    body: AdjustFYPRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_fyp_design_graph),
) -> StreamingResponse:
    """
    Redesign the FYP with one controlled adjustment (and an optional short note).

      404 — project not found
      409 — no design to adjust, all redesigns used, or a design is already running
      422 — not one of the controlled adjustments, or the note is too long
    """
    session = session_factory()
    return await _stream(
        session,
        lambda: start_fyp_redesign(workspace_id, body.adjustment, body.note, WorkspaceBrainRepository(session), graph),
    )


@router.post("/{workspace_id}/fyp-design/approve", response_model=GreyEvent)
async def approve_fyp_design(
    workspace_id: str,
    body: ApproveFYPRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_fyp_design_graph),
) -> GreyEvent:
    """
    Approve the current FYP design. Release 0.5 ends here.

      404 — project not found
      409 — no design to approve, not the current design, or a redesign is running
    """
    try:
        return await approve_fyp(workspace_id, body.design_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/fyp-design", response_model=FYPDesignResponse)
async def get_fyp_design(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> FYPDesignResponse:
    """Return the area, the current design with "Why this FYP?", redesigns left, and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return FYPDesignResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        fyp=build_fyp_view(snapshot),
        latest_run=snapshot.fyp_design_run,
    )
