"""
Project definition runner (Release 0.6) — writes the definition, applies the
student's scope changes and records the approval.

Like the other runners, it connects pieces without containing their logic:

    Project Brain (repository)  — checks the project, records each run, saves the
                                  definition, each scope change and the approval
    Project Definition graph    — runs define_project (a skill, via the Skill
                                  Registry) and pauses at scope_review
    Project definition events   — turns progress and results into GreyEvents

Usage (from API routes):

    session = await start_project_definition(workspace_id, repo, graph)
    async for event in session.events():
        ...  # send each GreyEvent to the browser

    event = await move_scope(workspace_id, item_id, to, repo, graph)
    event = await approve_scope(workspace_id, definition_id, repo, graph)

start_project_definition() checks everything first, so problems are raised
as errors before any event is sent. events() never raises: a failure becomes
project_definition_failed and the run is marked failed.

Restart safety: the paused workflow lives in memory and is lost on restart.
Before a move or approval the runner checks the workflow's position against
the Project Brain and rebuilds it if they differ. A run left "running" by a
stopped server is marked failed when the student tries again.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.repository import ProjectDefinitionRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    FunctionalArea,
    FYPDesign,
    FYPDesignStatus,
    ProjectDefinition,
    ProjectDefinitionRun,
    ProjectDefinitionRunStatus,
    ProjectDefinitionStatus,
    ScopeKind,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.brain.scope_rules import move_scope_item
from app.core.events import GreyEvent
from app.domains.fyp.skills.define_project import DefinitionProgress
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.project_definition.events import (
    ProjectDefinitionEventBuilder,
    scope_approved_event,
    scope_updated_event,
)
from app.domains.fyp.workflows.project_definition.graph import DEFINE_PROJECT_NODE, SCOPE_REVIEW_NODE
from app.domains.fyp.workflows.project_definition.nodes import APPROVE, DEFINITION_PROGRESS_KIND, MOVE
from app.domains.fyp.workflows.project_definition.view import build_definition_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the project definition finished."

# Projects whose definition is being written in THIS process right now.
_active_definitions: set[str] = set()


class ProjectDefinitionNotAllowedError(ValueError):
    """The project is not at a point where this definition or scope step is allowed."""


@dataclass
class ProjectDefinitionSession:
    """An attempt at writing the definition that has been checked and started. Call events() to run it."""

    workspace_id: str
    run: ProjectDefinitionRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: ProjectDefinitionEventBuilder
    _graph_input: dict

    async def events(self) -> AsyncIterator[GreyEvent]:
        """
        Run the definition and yield events in order:

            project_definition_started → project_definition_progress …
            → project_definition_progress (saving) → project_definition_ready

        or, if anything fails, project_definition_failed. Never raises.
        """
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()

            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == DEFINITION_PROGRESS_KIND:
                    yield self._builder.progress(DefinitionProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and DEFINE_PROJECT_NODE in chunk:
                    update = chunk[DEFINE_PROJECT_NODE]

            if update is None:
                raise RuntimeError("The project definition workflow finished without a definition.")

            yield self._builder.saving()
            output = update["definition_output"]
            await self._repo.complete_project_definition_run(
                self.run.id,
                ProjectDefinition.model_validate(output["definition"]),
                definition_id=update["definition_id"],
                item_ids=[item["id"] for item in update["scope"]],     # same order as the skill's scope
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_project_definition_run(self.workspace_id)
            yield self._builder.ready(build_definition_view(await self._repo.get_snapshot(self.workspace_id)))

        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_project_definition_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed()

        finally:
            # Runs even if the browser disconnects mid-stream. The run then stays
            # "running" in the database and is replaced on the next attempt.
            _active_definitions.discard(self.workspace_id)


async def start_project_definition(
    workspace_id: str, repo: WorkspaceBrainRepository, graph
) -> ProjectDefinitionSession:
    """
    Check the project and start writing its definition (or retry after a failure).

    Raises:
        ProjectNotFoundError:                     the project does not exist.
        ProjectDefinitionNotAllowedError:         the FYP isn't approved yet, or it is already defined.
        ProjectDefinitionRunAlreadyRunningError:  the definition is already being written.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    design = snapshot.fyp_design
    if (
        snapshot.workflow_state != WorkflowState.APPROVED_FYP
        or design is None
        or design.status != FYPDesignStatus.APPROVED
        or snapshot.project_definition is not None
    ):
        raise ProjectDefinitionNotAllowedError(
            f"The project can only be defined right after the FYP is approved (stage: {snapshot.workflow_state.value})."
        )

    if workspace_id in _active_definitions:
        raise ProjectDefinitionRunAlreadyRunningError(
            f"The project definition is already being written for '{workspace_id}'."
        )
    _active_definitions.add(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_project_definition_run(workspace_id)
    except BaseException:
        _active_definitions.discard(workspace_id)
        raise

    return ProjectDefinitionSession(
        workspace_id=workspace_id,
        run=run,
        _repo=repo,
        _graph=graph,
        _builder=ProjectDefinitionEventBuilder(workspace_id, snapshot.industry, snapshot.branch),
        _graph_input=_workflow_values(snapshot),                  # a fresh run from the start
    )


async def move_scope(
    workspace_id: str, item_id: str, to: ScopeKind, repo: WorkspaceBrainRepository, graph
) -> GreyEvent:
    """
    Move one feature to another list (HITL resume), then save it to the Brain.

    Raises:
        ProjectNotFoundError:             the project does not exist.
        ProjectDefinitionNotAllowedError: there is no scope to review right now.
        ScopeChangeError:                 the move breaks a scope rule.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    definition = _require_draft(snapshot)
    move_scope_item(definition.scope, item_id, to)          # check the rule before touching the workflow

    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": MOVE, "item_id": item_id, "to": to.value}), config=_config(workspace_id))

    updated = await repo.move_scope_item(workspace_id, item_id, to)
    moved = next(item for item in updated.scope if item.id == item_id)
    return scope_updated_event(workspace_id, build_definition_view(await repo.get_snapshot(workspace_id)), moved.title)


async def approve_scope(workspace_id: str, definition_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """
    Apply the student's approval of the scope (HITL resume).

    Raises:
        ProjectNotFoundError:             the project does not exist.
        ProjectDefinitionNotAllowedError: no scope to approve, or `definition_id` isn't this project's.
    """
    snapshot = await _require_snapshot(repo, workspace_id)
    definition = _require_draft(snapshot)
    if definition.id != definition_id:
        raise ProjectDefinitionNotAllowedError(f"'{definition_id}' is not this project's definition.")

    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": APPROVE, "definition_id": definition_id}), config=_config(workspace_id))

    await repo.approve_project_definition(workspace_id, definition_id)
    return scope_approved_event(workspace_id, build_definition_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    definition = snapshot.project_definition
    if (
        snapshot.workflow_state != WorkflowState.SCOPE
        or definition is None
        or definition.status != ProjectDefinitionStatus.DRAFT
    ):
        raise ProjectDefinitionNotAllowedError(
            f"There is no project scope to review right now (stage: {snapshot.workflow_state.value})."
        )
    return definition


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    """A "running" run that this process isn't running was left by a stopped server."""
    run = snapshot.project_definition_run
    if run is not None and run.status == ProjectDefinitionRunStatus.RUNNING:
        await repo.fail_project_definition_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    """The workflow state that matches the Project Brain."""
    definition = snapshot.project_definition
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "area": FunctionalArea.model_validate(snapshot.functional_area.model_dump()).model_dump(mode="json"),
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "design": FYPDesign.model_validate(snapshot.fyp_design.model_dump()).model_dump(mode="json"),
        "definition_output": None,
        "definition_id": definition.id if definition else None,
        "scope": [item.model_dump(mode="json") for item in definition.scope] if definition else [],
        "approved_definition_id": None,
    }


def _scope_places(scope: list) -> list[tuple]:
    return [(item["id"], item["kind"], item["position"]) for item in scope]


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """
    Make sure the workflow is waiting inside scope_review with the Brain's
    definition and scope. If not (a restart…), rebuild it: record the definition
    as if define_project had just finished, then run up to the interrupt.
    Returns True if it had to be rebuilt.
    """
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == SCOPE_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if (
        waiting
        and state.values.get("definition_id") == values["definition_id"]
        and _scope_places(state.values.get("scope", [])) == _scope_places(values["scope"])
    ):
        return False

    await graph.aupdate_state(config, values, as_node=DEFINE_PROJECT_NODE)
    await graph.ainvoke(None, config=config)          # runs into scope_review's interrupt
    return True
