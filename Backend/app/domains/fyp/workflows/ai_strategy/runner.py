"""
AI strategy runner (Release 0.7) — runs the AI necessity check, the student's
re-checks and the approval.

Like the other runners, it connects pieces without containing their logic:

    Project Brain (repository) — checks the project, records each run, saves the
                                 strategy, each re-check and the approval
    AI Strategy graph          — runs plan_ai_strategy (a skill, via the Skill
                                 Registry) and pauses at strategy_review
    AI strategy events         — turns progress and results into GreyEvents

Usage (from API routes):

    session = await start_ai_strategy(workspace_id, repo, graph)
    session = await start_ai_recheck(workspace_id, preference, repo, graph)
    async for event in session.events():
        ...  # send each GreyEvent to the browser

    event = await approve_strategy(workspace_id, strategy_id, repo, graph)

start_*() check everything first, so problems are raised as errors before any
event is sent. events() never raises: a failure becomes ai_strategy_failed and
the run is marked failed (a failed re-check doesn't use one up).

Restart safety: the paused workflow lives in memory and is lost on restart.
Before a re-check or approval the runner checks the workflow's position
against the Project Brain and rebuilds it if they differ. A run left
"running" by a stopped server is marked failed when the student tries again.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.ai_strategy_rules import recheck_problem
from app.core.brain.repository import AIStrategyError, AIStrategyRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_AI_STRATEGY_RECHECKS,
    AIStrategy,
    AIStrategyPreference,
    AIStrategyRun,
    AIStrategyRunStatus,
    AIStrategyStatus,
    FunctionalArea,
    FYPDesign,
    ProjectDefinition,
    ProjectDefinitionStatus,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.skills.plan_ai_strategy import AIStrategyProgress
from app.domains.fyp.workflows.ai_strategy.events import AIStrategyEventBuilder, ai_strategy_approved_event
from app.domains.fyp.workflows.ai_strategy.graph import PLAN_AI_STRATEGY_NODE, STRATEGY_REVIEW_NODE
from app.domains.fyp.workflows.ai_strategy.nodes import AI_STRATEGY_PROGRESS_KIND, APPROVE, RECHECK
from app.domains.fyp.workflows.ai_strategy.view import build_ai_strategy_view
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError

INTERRUPTED_ERROR = "Interrupted: the server stopped before the AI necessity check finished."

# Projects whose AI necessity check is running in THIS process right now.
_active_checks: set[str] = set()


class AIStrategyNotAllowedError(ValueError):
    """The project is not at a point where this AI strategy step is allowed."""


@dataclass
class AIStrategySession:
    """A check or re-check that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: AIStrategyRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: AIStrategyEventBuilder
    _graph_input: object             # what the graph is run with (the start values, or a Command)

    async def events(self) -> AsyncIterator[GreyEvent]:
        """
        Run the check and yield events in order:

            ai_strategy_started → ai_strategy_progress …
            → ai_strategy_progress (saving) → ai_strategy_ready

        or, if anything fails, ai_strategy_failed. Never raises.
        """
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()

            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == AI_STRATEGY_PROGRESS_KIND:
                    yield self._builder.progress(AIStrategyProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and PLAN_AI_STRATEGY_NODE in chunk:
                    update = chunk[PLAN_AI_STRATEGY_NODE]

            if update is None:
                raise RuntimeError("The AI strategy workflow finished without a strategy.")

            yield self._builder.saving()
            output = update["strategy_output"]
            await self._repo.complete_ai_strategy_run(
                self.run.id,
                AIStrategy.model_validate(output["strategy"]),
                strategy_id=update["strategy_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_ai_strategy_run(self.workspace_id)
            yield self._builder.ready(build_ai_strategy_view(await self._repo.get_snapshot(self.workspace_id)))

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_ai_strategy_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed(build_ai_strategy_view(await self._repo.get_snapshot(self.workspace_id)))

        finally:
            # Runs even if the browser disconnects mid-stream. The run then stays
            # "running" in the database and is replaced on the next attempt.
            _active_checks.discard(self.workspace_id)


async def start_ai_strategy(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> AIStrategySession:
    """
    Check the project and start the first AI necessity check (or retry it after a failure).

    Raises:
        ProjectNotFoundError:               the project does not exist.
        AIStrategyNotAllowedError:          the scope isn't approved yet, or the AI need is already checked.
        AIStrategyRunAlreadyRunningError:   a check is already running.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    definition = snapshot.project_definition
    if (
        snapshot.workflow_state != WorkflowState.SCOPE_APPROVED
        or definition is None
        or definition.status != ProjectDefinitionStatus.APPROVED
        or snapshot.ai_strategy is not None
    ):
        raise AIStrategyNotAllowedError(
            f"Grey checks the AI need right after the scope is approved (stage: {snapshot.workflow_state.value})."
        )

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_ai_strategy_run(workspace_id)
    except BaseException:
        _active_checks.discard(workspace_id)
        raise

    return AIStrategySession(
        workspace_id=workspace_id,
        run=run,
        _repo=repo,
        _graph=graph,
        _builder=AIStrategyEventBuilder(workspace_id, snapshot.industry, snapshot.branch, recheck=False),
        _graph_input=_workflow_values(snapshot),                  # a fresh run from the start
    )


async def start_ai_recheck(
    workspace_id: str,
    preference: AIStrategyPreference,
    repo: WorkspaceBrainRepository,
    graph,
) -> AIStrategySession:
    """
    Check the project and start one re-check with the student's preference.

    Raises:
        ProjectNotFoundError:               the project does not exist.
        AIStrategyNotAllowedError:          no draft to check again, no re-checks left,
                                            or the preference makes no sense for it.
        AIStrategyRunAlreadyRunningError:   a check is already running.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    strategy = _require_draft(snapshot)
    if strategy.rechecks_used >= MAX_AI_STRATEGY_RECHECKS:
        raise AIStrategyNotAllowedError(
            f"All {MAX_AI_STRATEGY_RECHECKS} re-checks have been used. You can approve the AI strategy."
        )
    problem = recheck_problem(strategy.strategy, preference)
    if problem is not None:
        raise AIStrategyNotAllowedError(problem)

    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        await _position_at_review(graph, snapshot)
        run = await repo.start_ai_strategy_run(workspace_id, preference)
    except AIStrategyError as error:
        _active_checks.discard(workspace_id)
        raise AIStrategyNotAllowedError(str(error)) from error
    except BaseException:
        _active_checks.discard(workspace_id)
        raise

    return AIStrategySession(
        workspace_id=workspace_id,
        run=run,
        _repo=repo,
        _graph=graph,
        _builder=AIStrategyEventBuilder(workspace_id, snapshot.industry, snapshot.branch, recheck=True),
        _graph_input=Command(resume={"action": RECHECK, "preference": preference.value}),
    )


async def approve_strategy(workspace_id: str, strategy_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """
    Apply the student's approval of the AI strategy (HITL resume).

    Raises:
        ProjectNotFoundError:               the project does not exist.
        AIStrategyNotAllowedError:          no strategy to approve, or `strategy_id` isn't this project's.
        AIStrategyRunAlreadyRunningError:   a re-check is running right now.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    strategy = _require_draft(snapshot)
    if strategy.id != strategy_id:
        raise AIStrategyNotAllowedError(f"'{strategy_id}' is not this project's AI strategy.")
    if workspace_id in _active_checks:
        raise AIStrategyRunAlreadyRunningError(f"A re-check is running for '{workspace_id}'.")

    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": APPROVE, "strategy_id": strategy_id}), config=_config(workspace_id))

    await repo.approve_ai_strategy(workspace_id, strategy_id)
    return ai_strategy_approved_event(workspace_id, build_ai_strategy_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    strategy = snapshot.ai_strategy
    if (
        snapshot.workflow_state != WorkflowState.AI_STRATEGY
        or strategy is None
        or strategy.status != AIStrategyStatus.DRAFT
    ):
        raise AIStrategyNotAllowedError(
            f"There is no AI strategy to review right now (stage: {snapshot.workflow_state.value})."
        )
    return strategy


def _claim(workspace_id: str) -> None:
    """Claim the project for this process (check and claim together)."""
    if workspace_id in _active_checks:
        raise AIStrategyRunAlreadyRunningError(f"An AI necessity check is already running for '{workspace_id}'.")
    _active_checks.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    """A "running" run that this process isn't running was left by a stopped server."""
    run = snapshot.ai_strategy_run
    if run is not None and run.status == AIStrategyRunStatus.RUNNING:
        await repo.fail_ai_strategy_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    """The workflow state that matches the Project Brain."""
    definition = snapshot.project_definition
    strategy = snapshot.ai_strategy
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "area": FunctionalArea.model_validate(snapshot.functional_area.model_dump()).model_dump(mode="json"),
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "design": FYPDesign.model_validate(snapshot.fyp_design.model_dump()).model_dump(mode="json"),
        "definition": ProjectDefinition.model_validate(definition.model_dump()).model_dump(mode="json"),
        "strategy": strategy.strategy.model_dump(mode="json") if strategy else None,
        "strategy_id": strategy.id if strategy else None,
        "strategy_output": None,
        "rechecks_used": strategy.rechecks_used if strategy else 0,
        "preference": None,
        "approved_strategy_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """
    Make sure the workflow is waiting inside strategy_review with the Brain's
    strategy and re-check count. If not (a restart, a failed re-check…), rebuild
    it: record the strategy as if plan_ai_strategy had just finished, then run
    up to the interrupt. Returns True if it had to be rebuilt.
    """
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == STRATEGY_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if (
        waiting
        and state.values.get("strategy_id") == values["strategy_id"]
        and state.values.get("rechecks_used") == values["rechecks_used"]
        and state.values.get("strategy") == values["strategy"]
    ):
        return False

    await graph.aupdate_state(config, values, as_node=PLAN_AI_STRATEGY_NODE)
    await graph.ainvoke(None, config=config)          # runs into strategy_review's interrupt
    return True
