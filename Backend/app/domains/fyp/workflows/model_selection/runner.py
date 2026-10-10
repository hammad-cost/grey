"""
Model runner (Release 0.9) — runs the model search, the student's re-searches
and the approval. Same shape as the dataset runner (Release 0.8):

    session = await start_model_search(workspace_id, repo, graph)
    session = await start_model_research(workspace_id, preference, repo, graph)
    async for event in session.events(): ...
    event = await approve_model_plan(workspace_id, plan_id, repo, graph)

start_*() check everything first; events() never raises (a failure becomes
model_search_failed and the run is marked failed). Restart-safe: before a
re-search or approval the paused review is rebuilt from the Project Brain.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.model_rules import research_problem
from app.core.brain.repository import ModelError, ModelRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_MODEL_RESEARCHES,
    AIStrategy,
    DatasetPlanStatus,
    FunctionalArea,
    ModelCandidate,
    ModelPlan,
    ModelPlanStatus,
    ModelPreference,
    ModelRun,
    ModelRunStatus,
    ProjectDefinition,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.find_models import ModelProgress
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.model_selection.events import ModelEventBuilder, models_approved_event
from app.domains.fyp.workflows.model_selection.graph import FIND_MODELS_NODE, MODEL_REVIEW_NODE
from app.domains.fyp.workflows.model_selection.nodes import APPROVE, MODEL_PROGRESS_KIND, RESEARCH
from app.domains.fyp.workflows.model_selection.view import build_model_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the model search finished."

# Projects whose model search is running in THIS process right now.
_active_searches: set[str] = set()


class ModelNotAllowedError(ValueError):
    """The project is not at a point where this model step is allowed."""


@dataclass
class ModelSession:
    """A search or re-search that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: ModelRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: ModelEventBuilder
    _graph_input: object

    async def events(self) -> AsyncIterator[GreyEvent]:
        """model_search_started → model_search_progress … → models_ready (or model_search_failed). Never raises."""
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()
            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == MODEL_PROGRESS_KIND:
                    yield self._builder.progress(ModelProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and FIND_MODELS_NODE in chunk:
                    update = chunk[FIND_MODELS_NODE]
            if update is None:
                raise RuntimeError("The model workflow finished without a plan.")

            yield self._builder.saving()
            output = update["plan_output"]
            await self._repo.complete_model_run(
                self.run.id,
                ModelPlan.model_validate(output["plan"]),
                [ModelCandidate.model_validate(c) for c in output["candidates"]],
                searches_used=output["searches_used"],
                plan_id=update["plan_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_model_run(self.workspace_id)
            yield self._builder.ready(build_model_view(await self._repo.get_snapshot(self.workspace_id)))

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_model_run(
                self.run.id, f"{type(error).__name__}: {error}", searches_used=getattr(error, "searches_used", 0)
            )
            yield self._builder.failed(build_model_view(await self._repo.get_snapshot(self.workspace_id)))

        finally:
            _active_searches.discard(self.workspace_id)


async def start_model_search(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> ModelSession:
    """
    Check the project and start the first model search (or retry it after a failure).

    Raises: ProjectNotFoundError, ModelNotAllowedError, ModelRunAlreadyRunningError.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    dataset = snapshot.dataset_plan
    if (
        snapshot.workflow_state != WorkflowState.DATASET_SELECTED
        or dataset is None
        or dataset.status != DatasetPlanStatus.SELECTED
        or snapshot.model_plan is not None
    ):
        raise ModelNotAllowedError(
            f"Grey looks for models right after a dataset is selected (stage: {snapshot.workflow_state.value})."
        )
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_model_run(workspace_id)
    except BaseException:
        _active_searches.discard(workspace_id)
        raise
    return ModelSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=ModelEventBuilder(workspace_id, snapshot.industry, snapshot.branch, research=False),
        _graph_input=_workflow_values(snapshot, []),
    )


async def start_model_research(
    workspace_id: str, preference: ModelPreference, repo: WorkspaceBrainRepository, graph
) -> ModelSession:
    """
    Check the project and start one re-search ("look for other models").

    Raises: ProjectNotFoundError, ModelNotAllowedError, ModelRunAlreadyRunningError.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.researches_used >= MAX_MODEL_RESEARCHES:
        raise ModelNotAllowedError(
            f"All {MAX_MODEL_RESEARCHES} new searches have been used. You can approve the model plan."
        )
    problem = research_problem(plan.plan, preference)
    if problem is not None:
        raise ModelNotAllowedError(problem)

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        await _position_at_review(graph, repo, snapshot)
        run = await repo.start_model_run(workspace_id, preference)
    except ModelError as error:
        _active_searches.discard(workspace_id)
        raise ModelNotAllowedError(str(error)) from error
    except BaseException:
        _active_searches.discard(workspace_id)
        raise
    return ModelSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=ModelEventBuilder(workspace_id, snapshot.industry, snapshot.branch, research=True),
        _graph_input=Command(resume={"action": RESEARCH, "preference": preference.value}),
    )


async def approve_model_plan(workspace_id: str, plan_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """
    Apply the student's approval of the model plan (HITL resume).

    Raises: ProjectNotFoundError, ModelNotAllowedError, ModelRunAlreadyRunningError.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.id != plan_id:
        raise ModelNotAllowedError(f"'{plan_id}' is not this project's model plan.")
    if workspace_id in _active_searches:
        raise ModelRunAlreadyRunningError(f"A new model search is running for '{workspace_id}'.")

    await _position_at_review(graph, repo, snapshot)
    await graph.ainvoke(Command(resume={"action": APPROVE, "plan_id": plan_id}), config=_config(workspace_id))
    await repo.approve_model_plan(workspace_id, plan_id)
    return models_approved_event(workspace_id, build_model_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    plan = snapshot.model_plan
    if snapshot.workflow_state != WorkflowState.MODEL_SELECTION or plan is None or plan.status != ModelPlanStatus.DRAFT:
        raise ModelNotAllowedError(f"There is no model plan to review right now (stage: {snapshot.workflow_state.value}).")
    return plan


def _claim(workspace_id: str) -> None:
    if workspace_id in _active_searches:
        raise ModelRunAlreadyRunningError(f"A model search is already running for '{workspace_id}'.")
    _active_searches.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    run = snapshot.model_run
    if run is not None and run.status == ModelRunStatus.RUNNING:
        await repo.fail_model_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot, known: list[ModelCandidate]) -> dict:
    """The workflow state that matches the Project Brain."""
    plan = snapshot.model_plan
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "area": FunctionalArea.model_validate(snapshot.functional_area.model_dump()).model_dump(mode="json"),
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "definition": ProjectDefinition.model_validate(snapshot.project_definition.model_dump()).model_dump(mode="json"),
        "strategy": AIStrategy.model_validate(snapshot.ai_strategy.strategy).model_dump(mode="json"),
        "dataset": snapshot.dataset_plan.selected_option.model_dump(mode="json"),
        "plan": plan.plan.model_dump(mode="json") if plan else None,
        "plan_id": plan.id if plan else None,
        "plan_output": None,
        "known_candidates": [c.model_dump(mode="json") for c in known],
        "researches_used": plan.researches_used if plan else 0,
        "preference": None,
        "approved_plan_id": None,
    }


async def _position_at_review(graph, repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> bool:
    """Make sure the workflow waits inside model_review with the Brain's plan; rebuild it if not."""
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    known = await repo.list_model_candidates(snapshot.model_plan.run_id)
    values = _workflow_values(snapshot, known)
    waiting = bool(state.tasks) and state.tasks[0].name == MODEL_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if waiting and all(state.values.get(k) == values[k] for k in ("plan_id", "researches_used", "plan", "known_candidates")):
        return False
    await graph.aupdate_state(config, values, as_node=FIND_MODELS_NODE)
    await graph.ainvoke(None, config=config)
    return True
