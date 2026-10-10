"""
Dataset runner (Release 0.8) — runs the dataset search, the student's
re-searches and the selection.

Like the other runners, it connects pieces without containing their logic:

    Project Brain (repository) — checks the project, records each run (with the
                                 pages it found), saves the recommendation,
                                 each re-search and the selection
    Dataset Discovery graph    — runs find_datasets (a skill, via the Skill
                                 Registry) and pauses at dataset_review
    Dataset events             — turns progress and results into GreyEvents

Usage (from API routes):

    session = await start_dataset_search(workspace_id, repo, graph)
    session = await start_dataset_research(workspace_id, preference, repo, graph)
    async for event in session.events():
        ...  # send each GreyEvent to the browser

    event = await select_dataset_option(workspace_id, plan_id, choice, repo, graph)

start_*() check everything first, so problems are raised as errors before any
event is sent. events() never raises: a failure becomes dataset_search_failed
and the run is marked failed (a failed re-search doesn't use one up).

Restart safety: the paused workflow lives in memory and is lost on restart.
Before a re-search or selection the runner checks the workflow's position
against the Project Brain and rebuilds it if they differ. A run left
"running" by a stopped server is marked failed when the student tries again.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.dataset_rules import research_problem
from app.core.brain.repository import DatasetError, DatasetRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_DATASET_RESEARCHES,
    AIStrategy,
    AIStrategyStatus,
    DatasetCandidate,
    DatasetChoice,
    DatasetPlan,
    DatasetPlanStatus,
    DatasetPreference,
    DatasetRun,
    DatasetRunStatus,
    FunctionalArea,
    ProjectDefinition,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.find_datasets import DatasetProgress
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.workflows.dataset_discovery.events import DatasetEventBuilder, dataset_selected_event
from app.domains.fyp.workflows.dataset_discovery.graph import DATASET_REVIEW_NODE, FIND_DATASETS_NODE
from app.domains.fyp.workflows.dataset_discovery.nodes import DATASET_PROGRESS_KIND, RESEARCH, SELECT
from app.domains.fyp.workflows.dataset_discovery.view import build_dataset_view
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError

INTERRUPTED_ERROR = "Interrupted: the server stopped before the dataset search finished."

# Projects whose dataset search is running in THIS process right now.
_active_searches: set[str] = set()


class DatasetNotAllowedError(ValueError):
    """The project is not at a point where this dataset step is allowed."""


@dataclass
class DatasetSession:
    """A search or re-search that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: DatasetRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: DatasetEventBuilder
    _graph_input: object             # what the graph is run with (the start values, or a Command)

    async def events(self) -> AsyncIterator[GreyEvent]:
        """
        Run the search and yield events in order:

            dataset_search_started → dataset_search_progress …
            → dataset_search_progress (saving) → dataset_options_ready

        or, if anything fails, dataset_search_failed. Never raises.
        """
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()

            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == DATASET_PROGRESS_KIND:
                    yield self._builder.progress(DatasetProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and FIND_DATASETS_NODE in chunk:
                    update = chunk[FIND_DATASETS_NODE]

            if update is None:
                raise RuntimeError("The dataset workflow finished without a recommendation.")

            yield self._builder.saving()
            output = update["plan_output"]
            await self._repo.complete_dataset_run(
                self.run.id,
                DatasetPlan.model_validate(output["plan"]),
                [DatasetCandidate.model_validate(c) for c in output["candidates"]],
                searches_used=output["searches_used"],
                plan_id=update["plan_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_dataset_run(self.workspace_id)
            yield self._builder.ready(build_dataset_view(await self._repo.get_snapshot(self.workspace_id)))

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_dataset_run(
                self.run.id,
                f"{type(error).__name__}: {error}",
                searches_used=getattr(error, "searches_used", 0),
            )
            yield self._builder.failed(build_dataset_view(await self._repo.get_snapshot(self.workspace_id)))

        finally:
            # Runs even if the browser disconnects mid-stream. The run then stays
            # "running" in the database and is replaced on the next attempt.
            _active_searches.discard(self.workspace_id)


async def start_dataset_search(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> DatasetSession:
    """
    Check the project and start the first dataset search (or retry it after a failure).

    Raises:
        ProjectNotFoundError:            the project does not exist.
        DatasetNotAllowedError:          the AI strategy isn't approved yet, or datasets are already recommended.
        DatasetRunAlreadyRunningError:   a search is already running.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    strategy = snapshot.ai_strategy
    if (
        snapshot.workflow_state != WorkflowState.AI_STRATEGY_APPROVED
        or strategy is None
        or strategy.status != AIStrategyStatus.APPROVED
        or snapshot.dataset_plan is not None
    ):
        raise DatasetNotAllowedError(
            f"Grey looks for datasets right after the AI strategy is approved (stage: {snapshot.workflow_state.value})."
        )

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_dataset_run(workspace_id)
    except BaseException:
        _active_searches.discard(workspace_id)
        raise

    return DatasetSession(
        workspace_id=workspace_id,
        run=run,
        _repo=repo,
        _graph=graph,
        _builder=DatasetEventBuilder(workspace_id, snapshot.industry, snapshot.branch, research=False),
        _graph_input=_workflow_values(snapshot, []),                # a fresh run from the start
    )


async def start_dataset_research(
    workspace_id: str,
    preference: DatasetPreference,
    repo: WorkspaceBrainRepository,
    graph,
) -> DatasetSession:
    """
    Check the project and start one re-search with the student's preference.

    Raises:
        ProjectNotFoundError:            the project does not exist.
        DatasetNotAllowedError:          no draft to search again for, no re-searches left,
                                         or the preference makes no sense for it.
        DatasetRunAlreadyRunningError:   a search is already running.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.researches_used >= MAX_DATASET_RESEARCHES:
        raise DatasetNotAllowedError(
            f"All {MAX_DATASET_RESEARCHES} new searches have been used. You can select a dataset."
        )
    problem = research_problem(plan.plan, preference)
    if problem is not None:
        raise DatasetNotAllowedError(problem)

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        await _position_at_review(graph, repo, snapshot)
        run = await repo.start_dataset_run(workspace_id, preference)
    except DatasetError as error:
        _active_searches.discard(workspace_id)
        raise DatasetNotAllowedError(str(error)) from error
    except BaseException:
        _active_searches.discard(workspace_id)
        raise

    return DatasetSession(
        workspace_id=workspace_id,
        run=run,
        _repo=repo,
        _graph=graph,
        _builder=DatasetEventBuilder(workspace_id, snapshot.industry, snapshot.branch, research=True),
        _graph_input=Command(resume={"action": RESEARCH, "preference": preference.value}),
    )


async def select_dataset_option(
    workspace_id: str, plan_id: str, choice: DatasetChoice, repo: WorkspaceBrainRepository, graph
) -> GreyEvent:
    """
    Apply the student's selection of the primary or the alternative dataset (HITL resume).

    Raises:
        ProjectNotFoundError:            the project does not exist.
        DatasetNotAllowedError:          nothing to select from, or `plan_id` isn't this project's.
        DatasetRunAlreadyRunningError:   a re-search is running right now.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    plan = _require_draft(snapshot)
    if plan.id != plan_id:
        raise DatasetNotAllowedError(f"'{plan_id}' is not this project's dataset recommendation.")
    if workspace_id in _active_searches:
        raise DatasetRunAlreadyRunningError(f"A new dataset search is running for '{workspace_id}'.")

    await _position_at_review(graph, repo, snapshot)
    await graph.ainvoke(
        Command(resume={"action": SELECT, "plan_id": plan_id, "choice": choice.value}), config=_config(workspace_id)
    )

    await repo.select_dataset(workspace_id, plan_id, choice)
    return dataset_selected_event(workspace_id, build_dataset_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    plan = snapshot.dataset_plan
    if (
        snapshot.workflow_state != WorkflowState.DATASET_DISCOVERY
        or plan is None
        or plan.status != DatasetPlanStatus.DRAFT
    ):
        raise DatasetNotAllowedError(
            f"There are no datasets to review right now (stage: {snapshot.workflow_state.value})."
        )
    return plan


def _claim(workspace_id: str) -> None:
    """Claim the project for this process (check and claim together)."""
    if workspace_id in _active_searches:
        raise DatasetRunAlreadyRunningError(f"A dataset search is already running for '{workspace_id}'.")
    _active_searches.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    """A "running" run that this process isn't running was left by a stopped server."""
    run = snapshot.dataset_run
    if run is not None and run.status == DatasetRunStatus.RUNNING:
        await repo.fail_dataset_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot, known: list[DatasetCandidate]) -> dict:
    """The workflow state that matches the Project Brain."""
    definition = snapshot.project_definition
    plan = snapshot.dataset_plan
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "area": FunctionalArea.model_validate(snapshot.functional_area.model_dump()).model_dump(mode="json"),
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "definition": ProjectDefinition.model_validate(definition.model_dump()).model_dump(mode="json"),
        "strategy": AIStrategy.model_validate(snapshot.ai_strategy.strategy).model_dump(mode="json"),
        "plan": plan.plan.model_dump(mode="json") if plan else None,
        "plan_id": plan.id if plan else None,
        "plan_output": None,
        "known_candidates": [c.model_dump(mode="json") for c in known],
        "researches_used": plan.researches_used if plan else 0,
        "preference": None,
        "selected_choice": None,
    }


async def _position_at_review(graph, repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> bool:
    """
    Make sure the workflow is waiting inside dataset_review with the Brain's
    recommendation, re-search count and found pages. If not (a restart, a failed
    re-search…), rebuild it: record the recommendation as if find_datasets had
    just finished, then run up to the interrupt. Returns True if it had to be rebuilt.
    """
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    known = await repo.list_dataset_candidates(snapshot.dataset_plan.run_id)
    values = _workflow_values(snapshot, known)
    waiting = bool(state.tasks) and state.tasks[0].name == DATASET_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if (
        waiting
        and state.values.get("plan_id") == values["plan_id"]
        and state.values.get("researches_used") == values["researches_used"]
        and state.values.get("plan") == values["plan"]
        and state.values.get("known_candidates") == values["known_candidates"]
    ):
        return False

    await graph.aupdate_state(config, values, as_node=FIND_DATASETS_NODE)
    await graph.ainvoke(None, config=config)          # runs into dataset_review's interrupt
    return True
