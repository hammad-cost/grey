"""
Technical plan runner (Release 0.11) — runs the architecture + evaluation plan,
the student's redesigns and the approval. Same shape as the technology runner:

    session = await start_technical_plan(workspace_id, repo, graph)
    session = await start_architecture_redesign(workspace_id, preference, repo, graph)
    async for event in session.events(): ...
    event = await approve_technical_plan(workspace_id, plan_id, repo, graph)
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.repository import ArchitectureError, ArchitectureRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_ARCHITECTURE_REDESIGNS,
    AIStrategy,
    ArchitecturePreference,
    ArchitectureRun,
    ArchitectureRunStatus,
    FYPDesign,
    ProjectDefinition,
    TechnicalPlan,
    TechnicalPlanStatus,
    TechnologyPlanStatus,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.design_architecture import ArchitectureProgress
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.technical_plan.events import ArchitectureEventBuilder, technical_plan_approved_event
from app.domains.fyp.workflows.technical_plan.graph import ARCHITECTURE_REVIEW_NODE, DESIGN_ARCHITECTURE_NODE
from app.domains.fyp.workflows.technical_plan.nodes import APPROVE, ARCHITECTURE_PROGRESS_KIND, REDESIGN
from app.domains.fyp.workflows.technical_plan.view import build_technical_plan_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the architecture finished."

_active_designs: set[str] = set()


class ArchitectureNotAllowedError(ValueError):
    """The project is not at a point where this architecture step is allowed."""


@dataclass
class ArchitectureSession:
    workspace_id: str
    run: ArchitectureRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: ArchitectureEventBuilder
    _graph_input: object

    async def events(self) -> AsyncIterator[GreyEvent]:
        """architecture_started → architecture_progress … → architecture_ready (or _failed). Never raises."""
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()
            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == ARCHITECTURE_PROGRESS_KIND:
                    yield self._builder.progress(ArchitectureProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and DESIGN_ARCHITECTURE_NODE in chunk:
                    update = chunk[DESIGN_ARCHITECTURE_NODE]
            if update is None:
                raise RuntimeError("The architecture workflow finished without a plan.")
            yield self._builder.saving()
            output = update["plan_output"]
            await self._repo.complete_architecture_run(
                self.run.id,
                TechnicalPlan.model_validate(output["plan"]),
                plan_id=update["plan_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_architecture_run(self.workspace_id)
            yield self._builder.ready(build_technical_plan_view(await self._repo.get_snapshot(self.workspace_id)))
        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_architecture_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed(build_technical_plan_view(await self._repo.get_snapshot(self.workspace_id)))
        finally:
            _active_designs.discard(self.workspace_id)


async def start_technical_plan(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> ArchitectureSession:
    """Check the project and start the first technical plan (or retry). Raises ProjectNotFoundError,
    ArchitectureNotAllowedError, ArchitectureRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    technology = snapshot.technology_plan
    if (
        snapshot.workflow_state != WorkflowState.TECHNOLOGY_APPROVED
        or technology is None
        or technology.status != TechnologyPlanStatus.APPROVED
        or snapshot.technical_plan is not None
    ):
        raise ArchitectureNotAllowedError(
            f"Grey designs the architecture right after the technology plan is approved (stage: {snapshot.workflow_state.value})."
        )
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_architecture_run(workspace_id)
    except BaseException:
        _active_designs.discard(workspace_id)
        raise
    return ArchitectureSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=ArchitectureEventBuilder(workspace_id, snapshot.industry, snapshot.branch, redesign=False),
        _graph_input=_workflow_values(snapshot),
    )


async def start_architecture_redesign(
    workspace_id: str, preference: ArchitecturePreference, repo: WorkspaceBrainRepository, graph
) -> ArchitectureSession:
    """Check the project and start one redesign. Raises ProjectNotFoundError, ArchitectureNotAllowedError,
    ArchitectureRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.redesigns_used >= MAX_ARCHITECTURE_REDESIGNS:
        raise ArchitectureNotAllowedError(
            f"All {MAX_ARCHITECTURE_REDESIGNS} redesigns have been used. You can approve the technical plan."
        )
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        await _position_at_review(graph, snapshot)
        run = await repo.start_architecture_run(workspace_id, preference)
    except ArchitectureError as error:
        _active_designs.discard(workspace_id)
        raise ArchitectureNotAllowedError(str(error)) from error
    except BaseException:
        _active_designs.discard(workspace_id)
        raise
    return ArchitectureSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=ArchitectureEventBuilder(workspace_id, snapshot.industry, snapshot.branch, redesign=True),
        _graph_input=Command(resume={"action": REDESIGN, "preference": preference.value}),
    )


async def approve_technical_plan(workspace_id: str, plan_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """Apply the student's approval (HITL resume). Raises ProjectNotFoundError, ArchitectureNotAllowedError,
    ArchitectureRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.id != plan_id:
        raise ArchitectureNotAllowedError(f"'{plan_id}' is not this project's technical plan.")
    if workspace_id in _active_designs:
        raise ArchitectureRunAlreadyRunningError(f"A redesign is running for '{workspace_id}'.")
    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": APPROVE, "plan_id": plan_id}), config=_config(workspace_id))
    await repo.approve_technical_plan(workspace_id, plan_id)
    return technical_plan_approved_event(workspace_id, build_technical_plan_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    plan = snapshot.technical_plan
    if snapshot.workflow_state != WorkflowState.ARCHITECTURE or plan is None or plan.status != TechnicalPlanStatus.DRAFT:
        raise ArchitectureNotAllowedError(
            f"There is no technical plan to review right now (stage: {snapshot.workflow_state.value})."
        )
    return plan


def _claim(workspace_id: str) -> None:
    if workspace_id in _active_designs:
        raise ArchitectureRunAlreadyRunningError(f"An architecture is already being designed for '{workspace_id}'.")
    _active_designs.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    run = snapshot.architecture_run
    if run is not None and run.status == ArchitectureRunStatus.RUNNING:
        await repo.fail_architecture_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    plan = snapshot.technical_plan
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "design": FYPDesign.model_validate(snapshot.fyp_design.model_dump()).model_dump(mode="json"),
        "definition": ProjectDefinition.model_validate(snapshot.project_definition.model_dump()).model_dump(mode="json"),
        "strategy": AIStrategy.model_validate(snapshot.ai_strategy.strategy).model_dump(mode="json"),
        "dataset": snapshot.dataset_plan.selected_option.model_dump(mode="json"),
        "models": snapshot.model_plan.plan.model_dump(mode="json"),
        "technology": snapshot.technology_plan.plan.model_dump(mode="json"),
        "plan": plan.plan.model_dump(mode="json") if plan else None,
        "plan_id": plan.id if plan else None,
        "plan_output": None,
        "redesigns_used": plan.redesigns_used if plan else 0,
        "preference": None,
        "approved_plan_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """Make sure the workflow waits inside architecture_review with the Brain's plan; rebuild it if not."""
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == ARCHITECTURE_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if waiting and all(state.values.get(k) == values[k] for k in ("plan_id", "redesigns_used", "plan")):
        return False
    await graph.aupdate_state(config, values, as_node=DESIGN_ARCHITECTURE_NODE)
    await graph.ainvoke(None, config=config)
    return True
