"""
Problem runner — runs problem extraction and the student's problem selection.

Like the research runner, it connects pieces without containing their logic:

    Project Brain (repository) — checks the project, records the problem run,
                                 saves the options and the student's choice
    Discovery graph (LangGraph) — runs problem_extraction (the skill, via the
                                 Skill Registry) and pauses at problem_selection
    Problem events              — turns progress and results into GreyEvents

Usage (from API routes):

    session = await start_problem_extraction(workspace_id, repo, graph)
    async for event in session.events():
        ...  # send each GreyEvent to the browser

    event = await choose_problem(workspace_id, problem_id, repo, graph)

start_problem_extraction() checks everything first, so problems are raised
as errors before any event is sent. events() then never raises: a failure
becomes a problem_extraction_failed event and the run is marked failed.

The skill receives only a read-only EvidenceReader (through the LangGraph run
config). Only this runner writes to the Project Brain. The API passes a
SessionEvidenceReader, so a cancelled request can't leave the database locked;
tests may pass the repository itself.

Recovery after a restart:
  - The paused workflow lives in memory and is lost on restart. Before running,
    the runner rebuilds the workflow's position from the Project Brain.
  - A problem run left "running" by a stopped server is marked failed and a
    new run starts.
  - Selection works after a restart too: the pause is rebuilt from the options
    saved in the Brain before the student's choice is applied.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.readers import EvidenceReader
from app.core.brain.repository import (
    ProblemRunAlreadyRunningError,
    ProblemSelectionError,
    WorkspaceBrainRepository,
)
from app.core.brain.schemas import ProblemCandidate, ProblemRun, ProblemRunStatus, ResearchStatus, WorkflowState
from app.core.events import GreyEvent
from app.domains.fyp.skills.problem_extraction import NotEnoughEvidenceError, ProblemProgress
from app.domains.fyp.workflows.discovery.graph import (
    EVIDENCE_RESEARCH_NODE,
    PROBLEM_EXTRACTION_NODE,
    PROBLEM_SELECTION_NODE,
)
from app.domains.fyp.workflows.discovery.nodes import EVIDENCE_READER_KEY, PROBLEM_PROGRESS_KIND
from app.domains.fyp.workflows.discovery.problem_events import ProblemEventBuilder, problem_selected_event
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError

INTERRUPTED_ERROR = "Interrupted: the server stopped before problem extraction finished."

# Projects whose problem extraction is running in THIS process right now.
_active_extractions: set[str] = set()


class ProblemExtractionNotAllowedError(ValueError):
    """The project is not at a point where problems can be found (e.g. research not finished)."""


@dataclass
class ProblemSession:
    """A problem-extraction run that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: ProblemRun
    recovered_workflow: bool        # True if the workflow position was rebuilt from the Brain
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: ProblemEventBuilder
    _evidence_reader: EvidenceReader

    async def events(self) -> AsyncIterator[GreyEvent]:
        """
        Run problem extraction and yield events in order:

            problem_extraction_started → problem_extraction_progress (several)
            → problem_options_ready

        or, if anything fails, problem_extraction_failed. Never raises.
        """
        config = {
            "configurable": {
                "thread_id": self.workspace_id,
                # Read-only access for the skill; never stored in the workflow state.
                EVIDENCE_READER_KEY: self._evidence_reader,
            }
        }
        try:
            yield self._builder.started()

            final_state: dict = {}
            async for mode, chunk in self._graph.astream(None, config, stream_mode=["custom", "values"]):
                if mode == "custom" and chunk.get("kind") == PROBLEM_PROGRESS_KIND:
                    yield self._builder.progress(ProblemProgress.model_validate(chunk["progress"]))
                elif mode == "values":
                    final_state = chunk

            output = final_state["problem_output"]
            yield self._builder.saving()
            self.run = await self._repo.complete_problem_run(
                self.run.id,
                [ProblemCandidate.model_validate(c) for c in output["candidates"]],
                candidate_ids=final_state["problem_candidate_ids"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
                candidates_generated=output["candidates_generated"],
                rejection_summary=output["rejection_summary"],
            )
            options = await self._repo.list_problem_candidates(self.workspace_id)

            yield self._builder.options_ready(self.run, options)

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_problem_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed(not_enough_evidence=isinstance(error, NotEnoughEvidenceError))

        finally:
            # Runs even if the browser disconnects mid-stream. The run then stays
            # "running" in the database and is replaced on the next attempt.
            _active_extractions.discard(self.workspace_id)


async def start_problem_extraction(
    workspace_id: str,
    repo: WorkspaceBrainRepository,
    graph,
    evidence_reader: EvidenceReader | None = None,
) -> ProblemSession:
    """
    Check the project, prepare the workflow, and record a new problem run.

    `evidence_reader` is what the skill reads evidence through (default: `repo`).

    Raises:
        ProjectNotFoundError:              the project does not exist.
        ProblemExtractionNotAllowedError:  research hasn't completed, or the
                                           project is past this stage.
        ProblemRunAlreadyRunningError:     extraction is already running.
    """
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    if (
        snapshot.workflow_state != WorkflowState.EVIDENCE_RESEARCH
        or not snapshot.industry
        or not snapshot.branch
        or snapshot.research is None
        or snapshot.research.status != ResearchStatus.COMPLETE
    ):
        raise ProblemExtractionNotAllowedError(
            "Problems can only be found after evidence research has completed."
        )

    # Claim the project for this process (check and claim together).
    if workspace_id in _active_extractions:
        raise ProblemRunAlreadyRunningError(f"Problem extraction is already running for '{workspace_id}'.")
    _active_extractions.add(workspace_id)

    try:
        # A "running" run that this process isn't running was left by a stopped server.
        if snapshot.problem_run is not None and snapshot.problem_run.status == ProblemRunStatus.RUNNING:
            await repo.fail_problem_run(snapshot.problem_run.id, INTERRUPTED_ERROR)

        recovered = await _position_before_extraction(graph, workspace_id, snapshot.industry, snapshot.branch)
        run = await repo.start_problem_run(workspace_id, snapshot.research.id)
    except BaseException:
        _active_extractions.discard(workspace_id)
        raise

    return ProblemSession(
        workspace_id=workspace_id,
        run=run,
        recovered_workflow=recovered,
        _repo=repo,
        _graph=graph,
        _builder=ProblemEventBuilder(workspace_id, snapshot.industry, snapshot.branch),
        _evidence_reader=evidence_reader or repo,
    )


async def choose_problem(
    workspace_id: str,
    problem_id: str,
    repo: WorkspaceBrainRepository,
    graph,
) -> GreyEvent:
    """
    Apply the student's mandatory problem choice (HITL resume).

    1. Checks the project is choosing a problem and the id is one of its options.
    2. Makes sure the workflow is paused at problem_selection with the SAME
       options as the Brain (rebuilt after a restart).
    3. Resumes the workflow with the choice; the node checks it again.
    4. Saves the choice in the Project Brain (stage → PROBLEM_SELECTED).

    Raises:
        ProjectNotFoundError:   the project does not exist.
        ProblemSelectionError:  not choosing a problem now, or not one of its options.
    """
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    if snapshot.workflow_state != WorkflowState.PROBLEM_OPTIONS:
        raise ProblemSelectionError(
            f"Project '{workspace_id}' is not choosing a problem (stage: {snapshot.workflow_state.value})."
        )
    options = await repo.list_problem_candidates(workspace_id)
    option_ids = [option.id for option in options]
    if problem_id not in option_ids:
        raise ProblemSelectionError(f"'{problem_id}' is not one of this project's problem options.")

    config = {"configurable": {"thread_id": workspace_id}}
    await _position_at_selection(graph, config, snapshot.industry, snapshot.branch, option_ids)
    await graph.ainvoke(Command(resume=problem_id), config=config)

    selected = await repo.select_problem(workspace_id, problem_id)
    return problem_selected_event(workspace_id, selected)


# ── Workflow positioning ──────────────────────────────────────────────────────

def _workflow_values(industry: str, branch: str) -> dict:
    return {
        "industry": industry,
        "branch": branch,
        "workflow_state": WorkflowState.EVIDENCE_RESEARCH.value,
        "problem_output": None,
        "problem_candidate_ids": [],
        "selected_problem_id": None,
    }


async def _position_before_extraction(graph, workspace_id: str, industry: str, branch: str) -> bool:
    """
    Make sure the workflow is paused right before problem_extraction for the
    industry and branch in the Project Brain. Returns True if it had to be rebuilt
    (after a restart, a retry, or if the Brain changed).
    """
    config = {"configurable": {"thread_id": workspace_id}}
    state = await graph.aget_state(config)
    if (
        state.next == (PROBLEM_EXTRACTION_NODE,)
        and state.values.get("industry") == industry
        and state.values.get("branch") == branch
    ):
        return False

    # Record the Brain's position as if evidence research had just finished.
    await graph.aupdate_state(
        config,
        {"workspace_id": workspace_id, "research_output": None, **_workflow_values(industry, branch)},
        as_node=EVIDENCE_RESEARCH_NODE,
    )
    return True


async def _position_at_selection(graph, config: dict, industry: str, branch: str, option_ids: list[str]) -> None:
    """
    Make sure the workflow is waiting inside problem_selection with exactly the
    Brain's options. If not (e.g. after a restart), rebuild it: record the options
    as if problem_extraction had just finished, then run up to the interrupt.
    """
    state = await graph.aget_state(config)
    waiting = bool(state.tasks) and state.tasks[0].name == PROBLEM_SELECTION_NODE and state.tasks[0].interrupts
    if waiting and state.values.get("problem_candidate_ids") == option_ids:
        return

    await graph.aupdate_state(
        config,
        {
            "workspace_id": config["configurable"]["thread_id"],
            **_workflow_values(industry, branch),
            "workflow_state": WorkflowState.PROBLEM_OPTIONS.value,
            "problem_candidate_ids": option_ids,
        },
        as_node=PROBLEM_EXTRACTION_NODE,
    )
    await graph.ainvoke(None, config=config)     # runs into problem_selection's interrupt
