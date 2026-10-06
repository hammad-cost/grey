"""
FYP design runner (Release 0.5) — runs the design, redesigns and approval.

Like the discovery runners, it connects pieces without containing their logic:

    Project Brain (repository) — checks the project, records each run, saves the
                                 area, each design version and the approval
    FYP Design graph           — runs classify_area and design_fyp (skills, via
                                 the Skill Registry) and pauses at fyp_review
    FYP design events          — turns progress and results into GreyEvents

Usage (from API routes):

    session = await start_fyp_design(workspace_id, repo, graph)
    session = await start_fyp_redesign(workspace_id, adjustment, note, repo, graph)
    async for event in session.events():
        ...  # send each GreyEvent to the browser

    event = await approve_fyp(workspace_id, design_id, repo, graph)

start_*() check everything first, so problems are raised as errors before any
event is sent. events() never raises: a failure becomes fyp_design_failed and
the run is marked failed (a failed redesign doesn't use up an adjustment).

Restart safety: the paused workflow lives in memory and is lost on restart.
Before every step the runner checks the workflow's position against the
Project Brain and rebuilds it if they differ:
  - a first design after a failure skips the area if it is already saved
  - a redesign or approval rebuilds the review pause with the Brain's draft
  - a design run left "running" by a stopped server is marked failed
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.repository import FYPDesignError, FYPDesignRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_FYP_ADJUSTMENTS,
    FYPAdjustment,
    FYPDesign,
    FYPDesignRun,
    FYPDesignRunKind,
    FYPDesignRunStatus,
    FYPDesignStatus,
    FunctionalArea,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.fyp_design_shared import DesignProgress, brief_from_problem
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.fyp_design.events import FYPDesignEventBuilder, fyp_approved_event
from app.domains.fyp.workflows.fyp_design.graph import (
    AREA_CLASSIFICATION_NODE,
    FYP_DESIGN_NODE,
    FYP_REVIEW_NODE,
)
from app.domains.fyp.workflows.fyp_design.nodes import ADJUST, APPROVE, DESIGN_PROGRESS_KIND
from app.domains.fyp.workflows.fyp_design.view import build_fyp_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the FYP design finished."

# Projects whose FYP design is running in THIS process right now.
_active_designs: set[str] = set()


class FYPDesignNotAllowedError(ValueError):
    """The project is not at a point where this FYP design step is allowed."""


@dataclass
class FYPDesignSession:
    """A design or redesign run that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: FYPDesignRun
    recovered_workflow: bool         # True if the workflow position was rebuilt from the Brain
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: FYPDesignEventBuilder
    _graph_input: object             # what the graph is run with (None, or a Command)

    async def events(self) -> AsyncIterator[GreyEvent]:
        """
        Run the design and yield events in order:

            fyp_design_started → fyp_design_progress … (→ area_classified)
            → fyp_design_progress (saving) → fyp_direction_ready

        or, if anything fails, fyp_design_failed. Never raises.
        """
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()

            design_output: dict | None = None
            design_id: str | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == DESIGN_PROGRESS_KIND:
                    yield self._builder.progress(DesignProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and AREA_CLASSIFICATION_NODE in chunk:
                    output = chunk[AREA_CLASSIFICATION_NODE]["area_output"]
                    area = await self._repo.save_functional_area(
                        self.run.id,
                        FunctionalArea.model_validate(output["area"]),
                        provider=output["provider"],
                        model=output["model"],
                        prompt_version=output["prompt_version"],
                    )
                    yield self._builder.area_classified(area)
                elif mode == "updates" and FYP_DESIGN_NODE in chunk:
                    design_output = chunk[FYP_DESIGN_NODE]["design_output"]
                    design_id = chunk[FYP_DESIGN_NODE]["design_id"]

            if design_output is None:
                raise RuntimeError("The FYP design workflow finished without a design.")

            yield self._builder.saving()
            await self._repo.complete_fyp_design_run(
                self.run.id,
                FYPDesign.model_validate(design_output["design"]),
                design_id=design_id,
                provider=design_output["provider"],
                model=design_output["model"],
                prompt_version=design_output["prompt_version"],
            )
            self.run = await self._repo.get_latest_fyp_design_run(self.workspace_id)
            yield self._builder.direction_ready(build_fyp_view(await self._repo.get_snapshot(self.workspace_id)))

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_fyp_design_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed(build_fyp_view(await self._repo.get_snapshot(self.workspace_id)))

        finally:
            # Runs even if the browser disconnects mid-stream. The run then stays
            # "running" in the database and is replaced on the next attempt.
            _active_designs.discard(self.workspace_id)


async def start_fyp_design(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> FYPDesignSession:
    """
    Check the project and start the first FYP design (or retry it after a failure).

    Raises:
        ProjectNotFoundError:             the project does not exist.
        FYPDesignNotAllowedError:         no problem chosen yet, or the FYP is already designed.
        FYPDesignRunAlreadyRunningError:  a design is already running.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    stages = (WorkflowState.PROBLEM_SELECTED, WorkflowState.AREA_CLASSIFICATION)
    if snapshot.selected_problem is None or snapshot.workflow_state not in stages or snapshot.fyp_design is not None:
        raise FYPDesignNotAllowedError(
            f"The FYP can only be designed right after a problem is chosen (stage: {snapshot.workflow_state.value})."
        )

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        values = _workflow_values(snapshot)
        config = _config(workspace_id)
        if snapshot.functional_area is not None:
            # The area was saved by an earlier attempt: continue from the design step.
            await graph.aupdate_state(config, values, as_node=AREA_CLASSIFICATION_NODE)
            graph_input, recovered = None, True
        else:
            graph_input, recovered = values, False           # a fresh run from the start
        run = await repo.start_fyp_design_run(workspace_id, FYPDesignRunKind.INITIAL)
    except BaseException:
        _active_designs.discard(workspace_id)
        raise

    return FYPDesignSession(
        workspace_id=workspace_id,
        run=run,
        recovered_workflow=recovered,
        _repo=repo,
        _graph=graph,
        _builder=FYPDesignEventBuilder(
            workspace_id, snapshot.industry, snapshot.branch, FYPDesignRunKind.INITIAL, snapshot.workflow_state,
        ),
        _graph_input=graph_input,
    )


async def start_fyp_redesign(
    workspace_id: str,
    adjustment: FYPAdjustment,
    note: str | None,
    repo: WorkspaceBrainRepository,
    graph,
) -> FYPDesignSession:
    """
    Check the project and start one controlled redesign of the current draft.

    Raises:
        ProjectNotFoundError:             the project does not exist.
        FYPDesignNotAllowedError:         no draft to adjust, or all redesigns are used.
        FYPDesignRunAlreadyRunningError:  a design is already running.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    _require_draft(snapshot)
    if snapshot.fyp_adjustments_used >= MAX_FYP_ADJUSTMENTS:
        raise FYPDesignNotAllowedError(f"All {MAX_FYP_ADJUSTMENTS} redesigns have been used. You can approve the FYP.")

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        recovered = await _position_at_review(graph, snapshot)
        note = (note or "").strip() or None
        run = await repo.start_fyp_design_run(workspace_id, FYPDesignRunKind.ADJUSTMENT, adjustment, note)
    except FYPDesignError as error:
        _active_designs.discard(workspace_id)
        raise FYPDesignNotAllowedError(str(error)) from error
    except BaseException:
        _active_designs.discard(workspace_id)
        raise

    return FYPDesignSession(
        workspace_id=workspace_id,
        run=run,
        recovered_workflow=recovered,
        _repo=repo,
        _graph=graph,
        _builder=FYPDesignEventBuilder(
            workspace_id, snapshot.industry, snapshot.branch, FYPDesignRunKind.ADJUSTMENT, WorkflowState.FYP_DESIGN,
        ),
        _graph_input=Command(resume={"action": ADJUST, "adjustment": adjustment.value, "note": note}),
    )


async def approve_fyp(workspace_id: str, design_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """
    Apply the student's approval of the current draft (HITL resume).

    Raises:
        ProjectNotFoundError:             the project does not exist.
        FYPDesignNotAllowedError:         no draft to approve, or `design_id` isn't the current draft.
        FYPDesignRunAlreadyRunningError:  a redesign is running right now.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    _require_draft(snapshot)
    if snapshot.fyp_design.id != design_id:
        raise FYPDesignNotAllowedError(f"'{design_id}' is not this project's current FYP design.")
    if workspace_id in _active_designs:
        raise FYPDesignRunAlreadyRunningError(f"A redesign is running for '{workspace_id}'.")

    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": APPROVE, "design_id": design_id}), config=_config(workspace_id))

    await repo.approve_fyp_design(workspace_id, design_id)
    return fyp_approved_event(workspace_id, build_fyp_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot) -> None:
    design = snapshot.fyp_design
    if snapshot.workflow_state != WorkflowState.FYP_DESIGN or design is None or design.status != FYPDesignStatus.DRAFT:
        raise FYPDesignNotAllowedError(
            f"There is no FYP design to review right now (stage: {snapshot.workflow_state.value})."
        )


def _claim(workspace_id: str) -> None:
    """Claim the project for this process (check and claim together)."""
    if workspace_id in _active_designs:
        raise FYPDesignRunAlreadyRunningError(f"An FYP design is already running for '{workspace_id}'.")
    _active_designs.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    """A "running" run that this process isn't running was left by a stopped server."""
    run = snapshot.fyp_design_run
    if run is not None and run.status == FYPDesignRunStatus.RUNNING:
        await repo.fail_fyp_design_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    """The workflow state that matches the Project Brain."""
    area = snapshot.functional_area
    design = snapshot.fyp_design
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "area": FunctionalArea.model_validate(area.model_dump()).model_dump(mode="json") if area else None,
        "area_output": None,
        "design": FYPDesign.model_validate(design.model_dump()).model_dump(mode="json") if design else None,
        "design_output": None,
        "design_id": design.id if design else None,
        "adjustments_used": snapshot.fyp_adjustments_used,
        "adjustment": None,
        "approved_design_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """
    Make sure the workflow is waiting inside fyp_review with the Brain's current
    draft and redesign count. If not (a restart, a failed redesign…), rebuild it:
    record the draft as if fyp_design had just finished, then run up to the
    interrupt. Returns True if it had to be rebuilt.
    """
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    waiting = bool(state.tasks) and state.tasks[0].name == FYP_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if (
        waiting
        and state.values.get("design_id") == snapshot.fyp_design.id
        and state.values.get("adjustments_used") == snapshot.fyp_adjustments_used
    ):
        return False

    await graph.aupdate_state(config, _workflow_values(snapshot), as_node=FYP_DESIGN_NODE)
    await graph.ainvoke(None, config=config)          # runs into fyp_review's interrupt
    return True
