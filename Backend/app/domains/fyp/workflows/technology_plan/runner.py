"""
Technology runner (Release 0.10) — runs the technology plan, the student's
re-plans and the approval. Same shape as the AI strategy runner (Release 0.7):

    session = await start_technology_plan(workspace_id, repo, graph)
    session = await start_technology_replan(workspace_id, preference, repo, graph)
    async for event in session.events(): ...
    event = await approve_technology(workspace_id, plan_id, repo, graph)
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.repository import TechnologyError, TechnologyRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_TECHNOLOGY_REPLANS,
    AIStrategy,
    FunctionalArea,
    FYPDesign,
    ModelPlanStatus,
    ProjectDefinition,
    TechnologyPlan,
    TechnologyPlanStatus,
    TechnologyPreference,
    TechnologyRun,
    TechnologyRunStatus,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.skills.plan_technology import TechnologyProgress
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.technology_plan.events import TechnologyEventBuilder, technology_approved_event
from app.domains.fyp.workflows.technology_plan.graph import PLAN_TECHNOLOGY_NODE, TECHNOLOGY_REVIEW_NODE
from app.domains.fyp.workflows.technology_plan.nodes import APPROVE, REPLAN, TECHNOLOGY_PROGRESS_KIND
from app.domains.fyp.workflows.technology_plan.view import build_technology_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the technology plan finished."

_active_plans: set[str] = set()


class TechnologyNotAllowedError(ValueError):
    """The project is not at a point where this technology step is allowed."""


@dataclass
class TechnologySession:
    workspace_id: str
    run: TechnologyRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: TechnologyEventBuilder
    _graph_input: object

    async def events(self) -> AsyncIterator[GreyEvent]:
        """technology_plan_started → _progress … → technology_plan_ready (or _failed). Never raises."""
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()
            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == TECHNOLOGY_PROGRESS_KIND:
                    yield self._builder.progress(TechnologyProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and PLAN_TECHNOLOGY_NODE in chunk:
                    update = chunk[PLAN_TECHNOLOGY_NODE]
            if update is None:
                raise RuntimeError("The technology workflow finished without a plan.")
            yield self._builder.saving()
            output = update["plan_output"]
            await self._repo.complete_technology_run(
                self.run.id,
                TechnologyPlan.model_validate(output["plan"]),
                plan_id=update["plan_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_technology_run(self.workspace_id)
            yield self._builder.ready(build_technology_view(await self._repo.get_snapshot(self.workspace_id)))
        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_technology_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed(build_technology_view(await self._repo.get_snapshot(self.workspace_id)))
        finally:
            _active_plans.discard(self.workspace_id)


async def start_technology_plan(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> TechnologySession:
    """Check the project and start the first technology plan (or retry). Raises ProjectNotFoundError,
    TechnologyNotAllowedError, TechnologyRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    models = snapshot.model_plan
    if (
        snapshot.workflow_state != WorkflowState.MODELS_APPROVED
        or models is None
        or models.status != ModelPlanStatus.APPROVED
        or snapshot.technology_plan is not None
    ):
        raise TechnologyNotAllowedError(
            f"Grey plans the technology right after the model plan is approved (stage: {snapshot.workflow_state.value})."
        )
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_technology_run(workspace_id)
    except BaseException:
        _active_plans.discard(workspace_id)
        raise
    return TechnologySession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=TechnologyEventBuilder(workspace_id, snapshot.industry, snapshot.branch, replan=False),
        _graph_input=_workflow_values(snapshot),
    )


async def start_technology_replan(
    workspace_id: str, preference: TechnologyPreference, repo: WorkspaceBrainRepository, graph
) -> TechnologySession:
    """Check the project and start one re-plan. Raises ProjectNotFoundError, TechnologyNotAllowedError,
    TechnologyRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.replans_used >= MAX_TECHNOLOGY_REPLANS:
        raise TechnologyNotAllowedError(
            f"All {MAX_TECHNOLOGY_REPLANS} re-plans have been used. You can approve the technology plan."
        )
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        await _position_at_review(graph, snapshot)
        run = await repo.start_technology_run(workspace_id, preference)
    except TechnologyError as error:
        _active_plans.discard(workspace_id)
        raise TechnologyNotAllowedError(str(error)) from error
    except BaseException:
        _active_plans.discard(workspace_id)
        raise
    return TechnologySession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=TechnologyEventBuilder(workspace_id, snapshot.industry, snapshot.branch, replan=True),
        _graph_input=Command(resume={"action": REPLAN, "preference": preference.value}),
    )


async def approve_technology(workspace_id: str, plan_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """Apply the student's approval (HITL resume). Raises ProjectNotFoundError, TechnologyNotAllowedError,
    TechnologyRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.id != plan_id:
        raise TechnologyNotAllowedError(f"'{plan_id}' is not this project's technology plan.")
    if workspace_id in _active_plans:
        raise TechnologyRunAlreadyRunningError(f"A re-plan is running for '{workspace_id}'.")
    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": APPROVE, "plan_id": plan_id}), config=_config(workspace_id))
    await repo.approve_technology_plan(workspace_id, plan_id)
    return technology_approved_event(workspace_id, build_technology_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    plan = snapshot.technology_plan
    if (
        snapshot.workflow_state != WorkflowState.TECHNOLOGY_PLAN
        or plan is None
        or plan.status != TechnologyPlanStatus.DRAFT
    ):
        raise TechnologyNotAllowedError(
            f"There is no technology plan to review right now (stage: {snapshot.workflow_state.value})."
        )
    return plan


def _claim(workspace_id: str) -> None:
    if workspace_id in _active_plans:
        raise TechnologyRunAlreadyRunningError(f"A technology plan is already running for '{workspace_id}'.")
    _active_plans.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    run = snapshot.technology_run
    if run is not None and run.status == TechnologyRunStatus.RUNNING:
        await repo.fail_technology_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    plan = snapshot.technology_plan
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "area": FunctionalArea.model_validate(snapshot.functional_area.model_dump()).model_dump(mode="json"),
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "design": FYPDesign.model_validate(snapshot.fyp_design.model_dump()).model_dump(mode="json"),
        "definition": ProjectDefinition.model_validate(snapshot.project_definition.model_dump()).model_dump(mode="json"),
        "strategy": AIStrategy.model_validate(snapshot.ai_strategy.strategy).model_dump(mode="json"),
        "dataset": snapshot.dataset_plan.selected_option.model_dump(mode="json"),
        "models": snapshot.model_plan.plan.model_dump(mode="json"),
        "plan": plan.plan.model_dump(mode="json") if plan else None,
        "plan_id": plan.id if plan else None,
        "plan_output": None,
        "replans_used": plan.replans_used if plan else 0,
        "preference": None,
        "approved_plan_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """Make sure the workflow waits inside technology_review with the Brain's plan; rebuild it if not."""
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == TECHNOLOGY_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if waiting and all(state.values.get(k) == values[k] for k in ("plan_id", "replans_used", "plan")):
        return False
    await graph.aupdate_state(config, values, as_node=PLAN_TECHNOLOGY_NODE)
    await graph.ainvoke(None, config=config)
    return True
