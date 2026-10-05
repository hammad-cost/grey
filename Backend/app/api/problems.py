"""
Problem API routes (Release 0.3).

  POST /projects/{id}/problems  — find problem options, streaming progress
  POST /projects/{id}/problem   — save the student's chosen problem (HITL resume)
  GET  /projects/{id}/problems  — read the current options and the choice

Rules (same as projects.py and research.py):
  - Routes stay thin. The problem runner does the work; routes only translate
    its errors into HTTP status codes and send its events.
  - Routes never call the LLM. Only the Problem Extraction skill does,
    through the LLM gateway, inside the workflow.

Streaming format: one GreyEvent per line as JSON (application/x-ndjson),
exactly like the research stream.

Why the extraction route opens its own database session: FastAPI closes
`Depends(get_session)` sessions before a streamed body is sent, but the
options are saved at the end of the stream.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import get_discovery_graph
from app.api.research import NDJSON_MEDIA_TYPE
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.readers import SessionEvidenceReader
from app.core.brain.repository import (
    ProblemRunAlreadyRunningError,
    ProblemSelectionError,
    WorkspaceBrainRepository,
)
from app.core.events import GreyEvent
from app.domains.fyp.schemas.requests import SelectProblemRequest
from app.domains.fyp.schemas.responses import ProblemListResponse
from app.domains.fyp.workflows.discovery import (
    ProblemExtractionNotAllowedError,
    ProjectNotFoundError,
    choose_problem,
    start_problem_extraction,
)

router = APIRouter(prefix="/projects", tags=["problems"])


@router.post("/{workspace_id}/problems")
async def find_problems(
    workspace_id: str,
    session_factory=Depends(get_session_factory),
    graph=Depends(get_discovery_graph),
) -> StreamingResponse:
    """
    Turn the project's evidence into problem options and stream progress events.

    Errors found before extraction starts are normal HTTP errors:
      404 — project not found
      409 — research not finished, options already exist, or extraction already running

    Once streaming has started the status is always 200; a failure is sent
    as a final `problem_extraction_failed` event instead.
    """
    session = session_factory()
    try:
        extraction = await start_problem_extraction(
            workspace_id,
            WorkspaceBrainRepository(session),
            graph,
            # The skill reads evidence in its own short session, so a closed tab can't lock the database.
            evidence_reader=SessionEvidenceReader(session_factory),
        )
    except ProjectNotFoundError as error:
        await session.close()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ProblemExtractionNotAllowedError, ProblemRunAlreadyRunningError) as error:
        await session.close()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except BaseException:
        await session.close()
        raise

    async def stream_events():
        try:
            async for event in extraction.events():
                yield event.model_dump_json() + "\n"
        finally:
            await session.close()

    return StreamingResponse(stream_events(), media_type=NDJSON_MEDIA_TYPE)


@router.post("/{workspace_id}/problem", response_model=GreyEvent)
async def select_problem(
    workspace_id: str,
    body: SelectProblemRequest,
    session: AsyncSession = Depends(get_session),
    graph=Depends(get_discovery_graph),
) -> GreyEvent:
    """
    Save the student's chosen problem and finish the discovery stage.

      404 — project not found
      409 — the project is not choosing a problem right now, or the id is not
            one of its options
    """
    try:
        return await choose_problem(workspace_id, body.problem_id, WorkspaceBrainRepository(session), graph)
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ProblemSelectionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{workspace_id}/problems", response_model=ProblemListResponse)
async def get_problems(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProblemListResponse:
    """Return the latest problem run, the current options (with sources) and the student's choice."""
    repo = WorkspaceBrainRepository(session)
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace_id}' not found.")

    return ProblemListResponse(
        workspace_id=workspace_id,
        problem_run=snapshot.problem_run,
        problems=await repo.list_problem_candidates(workspace_id),
        selected_problem_id=snapshot.selected_problem.id if snapshot.selected_problem else None,
    )
