"""
Supervisor readiness runner (Release 0.13) — prepares the supervisor brief and
applies the student's confirmation. Same shape as the feasibility runner:

    session = await start_supervisor_brief(workspace_id, repo, graph)
    async for event in session.events(): ...
    event = await confirm_supervisor_ready(workspace_id, brief_id, repo, graph)
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.repository import ReadinessRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    AIStrategy,
    FeasibilityStatus,
    FunctionalArea,
    FYPDesign,
    ProjectDefinition,
    ReadinessRun,
    ReadinessRunStatus,
    SupervisorBrief,
    SupervisorBriefStatus,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.skills.prepare_supervisor_brief import BriefProgress, SupervisorBriefInput
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.supervisor_readiness.events import SupervisorBriefEventBuilder, supervisor_ready_event
from app.domains.fyp.workflows.supervisor_readiness.graph import PREPARE_BRIEF_NODE, READINESS_REVIEW_NODE
from app.domains.fyp.workflows.supervisor_readiness.nodes import BRIEF_PROGRESS_KIND, CONFIRM
from app.domains.fyp.workflows.supervisor_readiness.view import build_supervisor_brief_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the supervisor brief finished."

_active_briefs: set[str] = set()


class ReadinessNotAllowedError(ValueError):
    """The project is not at a point where this supervisor readiness step is allowed."""


@dataclass
class SupervisorBriefSession:
    workspace_id: str
    run: ReadinessRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: SupervisorBriefEventBuilder
    _graph_input: object

    async def events(self) -> AsyncIterator[GreyEvent]:
        """supervisor_brief_started → _progress … → supervisor_readiness_ready (or _failed). Never raises."""
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()
            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == BRIEF_PROGRESS_KIND:
                    yield self._builder.progress(BriefProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and PREPARE_BRIEF_NODE in chunk:
                    update = chunk[PREPARE_BRIEF_NODE]
            if update is None:
                raise RuntimeError("The supervisor readiness workflow finished without a brief.")
            yield self._builder.saving()
            output = update["brief_output"]
            await self._repo.complete_readiness_run(
                self.run.id,
                SupervisorBrief.model_validate(output["brief"]),
                brief_id=update["brief_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_readiness_run(self.workspace_id)
            yield self._builder.ready(build_supervisor_brief_view(await self._repo.get_snapshot(self.workspace_id)))
        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_readiness_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed()
        finally:
            _active_briefs.discard(self.workspace_id)


def brief_input(snapshot: WorkspaceBrainSnapshot) -> SupervisorBriefInput:
    """Every approved decision, as the skill needs it."""
    return SupervisorBriefInput(
        workspace_id=snapshot.workspace_id,
        industry=snapshot.industry,
        branch=snapshot.branch,
        area=FunctionalArea.model_validate(snapshot.functional_area.model_dump()),
        problem=brief_from_problem(snapshot.selected_problem),
        evidence=snapshot.selected_problem.evidence,
        design=FYPDesign.model_validate(snapshot.fyp_design.model_dump()),
        definition=ProjectDefinition.model_validate(snapshot.project_definition.model_dump()),
        strategy=AIStrategy.model_validate(snapshot.ai_strategy.strategy),
        dataset=snapshot.dataset_plan.selected_option,
        models=snapshot.model_plan.plan,
        technology=snapshot.technology_plan.plan,
        technical=snapshot.technical_plan.plan,
        feasibility=snapshot.feasibility_report.report,
    )


async def start_supervisor_brief(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> SupervisorBriefSession:
    """Check the project and start the supervisor brief (or retry). Raises ProjectNotFoundError,
    ReadinessNotAllowedError, ReadinessRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    feasibility = snapshot.feasibility_report
    if (
        snapshot.workflow_state != WorkflowState.FEASIBILITY_ACCEPTED
        or feasibility is None
        or feasibility.status != FeasibilityStatus.ACCEPTED
        or snapshot.supervisor_brief is not None
    ):
        raise ReadinessNotAllowedError(
            f"Grey prepares the supervisor brief right after feasibility is accepted (stage: {snapshot.workflow_state.value})."
        )
    if workspace_id in _active_briefs:
        raise ReadinessRunAlreadyRunningError(f"A supervisor brief is already being prepared for '{workspace_id}'.")
    _active_briefs.add(workspace_id)
    try:
        run = snapshot.readiness_run
        if run is not None and run.status == ReadinessRunStatus.RUNNING:
            await repo.fail_readiness_run(run.id, INTERRUPTED_ERROR)
        run = await repo.start_readiness_run(workspace_id)
    except BaseException:
        _active_briefs.discard(workspace_id)
        raise
    return SupervisorBriefSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=SupervisorBriefEventBuilder(workspace_id, snapshot.industry, snapshot.branch),
        _graph_input=_workflow_values(snapshot),
    )


async def confirm_supervisor_ready(workspace_id: str, brief_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """Apply the student's confirmation (HITL resume). Raises ProjectNotFoundError, ReadinessNotAllowedError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    brief = snapshot.supervisor_brief
    if (
        snapshot.workflow_state != WorkflowState.SUPERVISOR_READINESS
        or brief is None
        or brief.status != SupervisorBriefStatus.DRAFT
    ):
        raise ReadinessNotAllowedError(
            f"There is no supervisor brief to confirm right now (stage: {snapshot.workflow_state.value})."
        )
    if brief.id != brief_id:
        raise ReadinessNotAllowedError(f"'{brief_id}' is not this project's supervisor brief.")
    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": CONFIRM, "brief_id": brief_id}), config=_config(workspace_id))
    await repo.confirm_supervisor_ready(workspace_id, brief_id)
    return supervisor_ready_event(workspace_id, build_supervisor_brief_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    brief = snapshot.supervisor_brief
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "inputs": brief_input(snapshot).model_dump(mode="json"),
        "brief": brief.brief.model_dump(mode="json") if brief else None,
        "brief_id": brief.id if brief else None,
        "brief_output": None,
        "confirmed_brief_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """Make sure the workflow waits inside readiness_review with the Brain's brief; rebuild it if not."""
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == READINESS_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if waiting and state.values.get("brief_id") == values["brief_id"] and state.values.get("brief") == values["brief"]:
        return False
    await graph.aupdate_state(config, values, as_node=PREPARE_BRIEF_NODE)
    await graph.ainvoke(None, config=config)
    return True
