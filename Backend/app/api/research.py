"""
Research API routes (Release 0.2).

  POST /projects/{id}/research  — run evidence research, streaming progress
  GET  /projects/{id}/evidence  — read the evidence saved in the Project Brain

Rules (same as projects.py):
  - Routes stay thin. The research runner does the work; routes only
    translate its errors into HTTP status codes and send its events.

Streaming format:
  The research route sends one GreyEvent per line as JSON
  ("newline-delimited JSON", media type application/x-ndjson).
  The frontend reads the response line by line and applies each event.

Why the research route opens its own database session:
  FastAPI closes `Depends(get_session)` sessions before a streamed body is
  sent, but research saves evidence at the end of the stream. So the route
  opens a session itself and closes it when the stream finishes.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import get_discovery_graph
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import ResearchAlreadyRunningError, WorkspaceBrainRepository
from app.core.config import settings
from app.core.tools import search_provider_label
from app.domains.fyp.schemas.responses import EvidenceListResponse
from app.domains.fyp.workflows.discovery import (
    ProjectNotFoundError,
    ResearchNotAllowedError,
    start_evidence_research,
)

router = APIRouter(prefix="/projects", tags=["research"])

NDJSON_MEDIA_TYPE = "application/x-ndjson"


@router.post("/{workspace_id}/research")
async def start_research(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_discovery_graph),
) -> StreamingResponse:
    """
    Run evidence research for the project and stream progress events.

    Errors found before research starts are normal HTTP errors:
      404 — project not found
      409 — no branch chosen yet, or research is already running

    Once streaming has started the status is always 200; a failure is sent
    as a final `research_failed` event instead.
    """
    session = session_factory()
    try:
        research = await start_evidence_research(
            workspace_id,
            WorkspaceBrainRepository(session),
            graph,
            provider_name=search_provider_label(settings),
        )
    except ProjectNotFoundError as error:
        await session.close()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ResearchNotAllowedError, ResearchAlreadyRunningError) as error:
        await session.close()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in research.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.get("/{workspace_id}/evidence", response_model=EvidenceListResponse)
async def get_evidence(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> EvidenceListResponse:
    """Return the latest research run and all saved evidence, strongest first."""
    repo = WorkspaceBrainRepository(session)
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")

    return EvidenceListResponse(
        workspace_id=workspace_id,
        research=snapshot.research,
        evidence=await repo.list_evidence(workspace_id),
    )
