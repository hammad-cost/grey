"""
Proposal routes (Release 0.14).

  POST /projects/{id}/proposal            — write the proposal, streaming progress
  POST /projects/{id}/proposal/rewrite    — rewrite one narrative section, streaming progress
  POST /projects/{id}/proposal/finalize   — the student finalizes it (HITL resume); the journey is COMPLETE
  GET  /projects/{id}/proposal            — the proposal and the latest attempt
  GET  /projects/{id}/proposal/markdown   — the proposal as a Markdown file to download

Routes stay thin: the proposal runner does the work.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.repository import ProposalRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import FinalizeProposalRequest, RewriteProposalSectionRequest
from app.domains.fyp.schemas.responses import ProposalResponse
from app.domains.fyp.skills.generate_proposal import proposal_markdown
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.proposal import (
    ProposalNotAllowedError,
    build_proposal_view,
    finalize_proposal,
    start_proposal,
    start_proposal_rewrite,
)
from app.domains.fyp.workflows.proposal.graph import proposal_graph as _proposal_graph

router = APIRouter(prefix="/projects", tags=["proposal"])

_EXPECTED_ERRORS = (ProjectNotFoundError, ProposalNotAllowedError, ProposalRunAlreadyRunningError)
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"


def get_proposal_graph():
    """The shared Proposal workflow graph. A dependency, so tests can swap it."""
    return _proposal_graph


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


@router.post("/{workspace_id}/proposal")
async def generate_proposal(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_proposal_graph),
) -> StreamingResponse:
    """Write the proposal. 404; 409 not ready for the supervisor / already written / running."""
    return await _stream(lambda repo: start_proposal(workspace_id, repo, graph), session_factory)


@router.post("/{workspace_id}/proposal/rewrite")
async def rewrite_section(
    workspace_id: str,
    body: RewriteProposalSectionRequest,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_proposal_graph),
) -> StreamingResponse:
    """Rewrite one narrative section (up to 3 times). 404; 409 nothing to review / none left / not rewritable; 422."""
    return await _stream(lambda repo: start_proposal_rewrite(workspace_id, body.section, repo, graph), session_factory)


@router.post("/{workspace_id}/proposal/finalize", response_model=GreyEvent)
async def finalize(
    workspace_id: str,
    body: FinalizeProposalRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_proposal_graph),
) -> GreyEvent:
    """Finalize the proposal. The FYP journey is complete. 404; 409 nothing to finalize / wrong id / running."""
    try:
        return await finalize_proposal(workspace_id, body.proposal_id, WorkspaceBrainRepository(session), graph)
    except _EXPECTED_ERRORS as error:
        raise _http_error(error) from error


@router.get("/{workspace_id}/proposal", response_model=ProposalResponse)
async def get_proposal(workspace_id: str, session: AsyncSession = Depends(get_session)) -> ProposalResponse:
    """Return the proposal (once written) and the latest attempt."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")
    return ProposalResponse(
        workspace_id=workspace_id,
        workflow_state=snapshot.workflow_state,
        proposal=build_proposal_view(snapshot),
        latest_run=snapshot.proposal_run,
    )


@router.get("/{workspace_id}/proposal/markdown", response_class=PlainTextResponse)
async def download_proposal(workspace_id: str, session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    """The proposal as a Markdown file. 404 when the project or its proposal doesn't exist yet."""
    snapshot = await WorkspaceBrainRepository(session).get_snapshot(workspace_id)
    if snapshot is None or snapshot.proposal is None:
        raise HTTPException(status_code=404, detail="There is no proposal to download yet.")
    return PlainTextResponse(
        proposal_markdown(snapshot.proposal.proposal),
        media_type=MARKDOWN_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="fyp-proposal.md"'},
    )
