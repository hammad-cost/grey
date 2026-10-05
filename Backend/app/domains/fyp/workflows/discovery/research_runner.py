"""
Research runner — runs the evidence_research step of the Discovery workflow.

It connects three things, without containing any research logic itself:

    Project Brain (repository)  — checks the project, records the research run,
                                  saves the evidence
    Discovery graph (LangGraph) — runs the evidence_research node, which calls
                                  the skill through the SkillRegistry
    Research events             — turns progress into GreyEvents for the frontend

Usage (from an API route):

    session = await start_evidence_research(workspace_id, repo, graph, provider_name="mock")
    async for event in session.events():
        ...  # send each GreyEvent to the browser

start_evidence_research() checks everything first, so problems (unknown
project, wrong stage, research already running) are raised as errors before
any event is sent. events() then never raises: a failure becomes a
research_failed event, and the run is marked failed in the Project Brain.

Recovery after a restart:
  - The paused workflow lives in memory (MemorySaver) and is lost on restart.
    Before running, the runner rebuilds the workflow's position from the
    Project Brain (industry + branch), so research still works.
  - A research run left "running" by a stopped server is marked failed and a
    new run starts, so the student is never blocked.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.core.brain.repository import ResearchAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import ResearchRun, ResearchStatus, WorkflowState
from app.core.events import GreyEvent
from app.domains.fyp.skills.research_evidence.schemas import (
    ResearchEvidenceOutput,
    ResearchProgress,
)
from app.domains.fyp.workflows.discovery.graph import BRANCH_SELECTION_NODE, EVIDENCE_RESEARCH_NODE
from app.domains.fyp.workflows.discovery.nodes import RESEARCH_PROGRESS_KIND
from app.domains.fyp.workflows.discovery.research_events import ResearchEventBuilder

INTERRUPTED_ERROR = "Interrupted: the server stopped before research finished."

# Projects whose research is running in THIS process right now.
# A run marked "running" in the database but not listed here was left behind
# by a previous process (e.g. after a restart) and can safely be replaced.
_active_research: set[str] = set()


class ProjectNotFoundError(LookupError):
    """The project does not exist."""


class ResearchNotAllowedError(ValueError):
    """The project is not at a point where research can run (e.g. no branch chosen yet)."""


@dataclass
class ResearchSession:
    """A research run that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: ResearchRun
    recovered_workflow: bool        # True if the workflow position was rebuilt from the Brain
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: ResearchEventBuilder

    async def events(self) -> AsyncIterator[GreyEvent]:
        """
        Run the research and yield events in order:

            research_started → searching_sources / sources_found (per category)
            → evaluating_evidence → storing_evidence → research_completed

        or, if anything fails, research_failed. Never raises.
        """
        config = {"configurable": {"thread_id": self.workspace_id}}
        try:
            yield self._builder.started()

            final_state: dict = {}
            async for mode, chunk in self._graph.astream(
                None, config, stream_mode=["custom", "values"]
            ):
                if mode == "custom" and chunk.get("kind") == RESEARCH_PROGRESS_KIND:
                    yield self._builder.progress(ResearchProgress.model_validate(chunk["progress"]))
                elif mode == "values":
                    final_state = chunk

            output = ResearchEvidenceOutput.model_validate(final_state["research_output"])

            yield self._builder.storing()
            self.run = await self._repo.complete_research_run(self.run.id, output.sources)

            yield self._builder.completed(self.run, output.summary)

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_research_run(
                self.run.id, f"{type(error).__name__}: {error}"
            )
            yield self._builder.failed()

        finally:
            # Runs even if the browser disconnects mid-stream. The run then stays
            # "running" in the database and is replaced on the next attempt.
            _active_research.discard(self.workspace_id)


async def start_evidence_research(
    workspace_id: str,
    repo: WorkspaceBrainRepository,
    graph,
    provider_name: str,
) -> ResearchSession:
    """
    Check the project, prepare the workflow, and record a new research run.

    Raises:
        ProjectNotFoundError:        the project does not exist.
        ResearchNotAllowedError:     the project is not at EVIDENCE_RESEARCH,
                                     or industry/branch are missing.
        ResearchAlreadyRunningError: research for this project is already running.
    """
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    if (
        snapshot.workflow_state != WorkflowState.EVIDENCE_RESEARCH
        or not snapshot.industry
        or not snapshot.branch
    ):
        raise ResearchNotAllowedError(
            "Research can only start after an industry and branch have been chosen."
        )

    # Claim the project for this process (check and claim happen together,
    # so two requests can't both start research for the same project).
    if workspace_id in _active_research:
        raise ResearchAlreadyRunningError(f"Research is already running for '{workspace_id}'.")
    _active_research.add(workspace_id)

    try:
        # A "running" run that this process isn't running was left by a stopped server.
        if snapshot.research is not None and snapshot.research.status == ResearchStatus.RUNNING:
            await repo.fail_research_run(snapshot.research.id, INTERRUPTED_ERROR)

        recovered = await _position_workflow_before_research(
            graph, workspace_id, snapshot.industry, snapshot.branch
        )
        run = await repo.start_research_run(workspace_id, provider=provider_name)
    except BaseException:
        _active_research.discard(workspace_id)
        raise

    return ResearchSession(
        workspace_id=workspace_id,
        run=run,
        recovered_workflow=recovered,
        _repo=repo,
        _graph=graph,
        _builder=ResearchEventBuilder(workspace_id, snapshot.industry, snapshot.branch),
    )


async def _position_workflow_before_research(graph, workspace_id: str, industry: str, branch: str) -> bool:
    """
    Make sure the workflow is paused right before evidence_research, for the
    industry and branch stored in the Project Brain.

    Normally it already is (the student just picked a branch). It needs
    rebuilding when:
      - the server restarted (in-memory workflow state was lost),
      - research already ran once and the student is running it again.

    Returns True if the position had to be rebuilt.
    """
    config = {"configurable": {"thread_id": workspace_id}}
    state = await graph.aget_state(config)

    already_in_place = (
        state.next == (EVIDENCE_RESEARCH_NODE,)
        and state.values.get("industry") == industry
        and state.values.get("branch") == branch
    )
    if already_in_place:
        return False

    # Record the Brain's decisions as if branch selection had just finished.
    # The graph's next step is then evidence_research, paused before it runs.
    await graph.aupdate_state(
        config,
        {
            "workspace_id": workspace_id,
            "workflow_state": WorkflowState.EVIDENCE_RESEARCH.value,
            "industry": industry,
            "branch": branch,
            "research_output": None,
        },
        as_node=BRANCH_SELECTION_NODE,
    )
    return True
