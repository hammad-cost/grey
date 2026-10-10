"""
Feasibility runner (Release 0.12) — runs the feasibility analysis and the student's acceptance.

    session = await start_feasibility(workspace_id, repo, graph)
    async for event in session.events(): ...
    event = await accept_feasibility_report(workspace_id, report_id, repo, graph)

start_feasibility() checks everything first; events() never raises (a failure
becomes feasibility_failed and the run is marked failed). Restart-safe: before
acceptance the paused review is rebuilt from the Project Brain.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.repository import FeasibilityRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    AIStrategy,
    FeasibilityReport,
    FeasibilityRun,
    FeasibilityRunStatus,
    FeasibilityStatus,
    FYPDesign,
    ProjectDefinition,
    TechnicalPlanStatus,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.assess_feasibility import FeasibilityProgress
from app.domains.fyp.skills.fyp_design_shared import brief_from_problem
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.feasibility.events import FeasibilityEventBuilder, feasibility_accepted_event
from app.domains.fyp.workflows.feasibility.graph import ASSESS_FEASIBILITY_NODE, FEASIBILITY_REVIEW_NODE
from app.domains.fyp.workflows.feasibility.nodes import ACCEPT, FEASIBILITY_PROGRESS_KIND
from app.domains.fyp.workflows.feasibility.view import build_feasibility_view

INTERRUPTED_ERROR = "Interrupted: the server stopped before the feasibility check finished."

_active_assessments: set[str] = set()


class FeasibilityNotAllowedError(ValueError):
    """The project is not at a point where this feasibility step is allowed."""


@dataclass
class FeasibilitySession:
    workspace_id: str
    run: FeasibilityRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: FeasibilityEventBuilder
    _graph_input: object

    async def events(self) -> AsyncIterator[GreyEvent]:
        """feasibility_started → feasibility_progress … → feasibility_ready (or feasibility_failed). Never raises."""
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()
            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == FEASIBILITY_PROGRESS_KIND:
                    yield self._builder.progress(FeasibilityProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and ASSESS_FEASIBILITY_NODE in chunk:
                    update = chunk[ASSESS_FEASIBILITY_NODE]
            if update is None:
                raise RuntimeError("The feasibility workflow finished without a report.")
            yield self._builder.saving()
            output = update["report_output"]
            await self._repo.complete_feasibility_run(
                self.run.id,
                FeasibilityReport.model_validate(output["report"]),
                report_id=update["report_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_feasibility_run(self.workspace_id)
            yield self._builder.ready(build_feasibility_view(await self._repo.get_snapshot(self.workspace_id)))
        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_feasibility_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed()
        finally:
            _active_assessments.discard(self.workspace_id)


async def start_feasibility(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> FeasibilitySession:
    """Check the project and start the feasibility analysis (or retry). Raises ProjectNotFoundError,
    FeasibilityNotAllowedError, FeasibilityRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    technical = snapshot.technical_plan
    if (
        snapshot.workflow_state != WorkflowState.TECHNICAL_PLAN_APPROVED
        or technical is None
        or technical.status != TechnicalPlanStatus.APPROVED
        or snapshot.feasibility_report is not None
    ):
        raise FeasibilityNotAllowedError(
            f"Grey checks feasibility right after the technical plan is approved (stage: {snapshot.workflow_state.value})."
        )
    if workspace_id in _active_assessments:
        raise FeasibilityRunAlreadyRunningError(f"A feasibility check is already running for '{workspace_id}'.")
    _active_assessments.add(workspace_id)
    try:
        run = snapshot.feasibility_run
        if run is not None and run.status == FeasibilityRunStatus.RUNNING:
            await repo.fail_feasibility_run(run.id, INTERRUPTED_ERROR)
        run = await repo.start_feasibility_run(workspace_id)
    except BaseException:
        _active_assessments.discard(workspace_id)
        raise
    return FeasibilitySession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=FeasibilityEventBuilder(workspace_id, snapshot.industry, snapshot.branch),
        _graph_input=_workflow_values(snapshot),
    )


async def accept_feasibility_report(
    workspace_id: str, report_id: str, repo: WorkspaceBrainRepository, graph
) -> GreyEvent:
    """Apply the student's acceptance (HITL resume). Raises ProjectNotFoundError, FeasibilityNotAllowedError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    report = snapshot.feasibility_report
    if snapshot.workflow_state != WorkflowState.FEASIBILITY or report is None or report.status != FeasibilityStatus.DRAFT:
        raise FeasibilityNotAllowedError(
            f"There is no feasibility report to accept right now (stage: {snapshot.workflow_state.value})."
        )
    if report.id != report_id:
        raise FeasibilityNotAllowedError(f"'{report_id}' is not this project's feasibility report.")
    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": ACCEPT, "report_id": report_id}), config=_config(workspace_id))
    await repo.accept_feasibility(workspace_id, report_id)
    return feasibility_accepted_event(workspace_id, build_feasibility_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    report = snapshot.feasibility_report
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "industry": snapshot.industry,
        "branch": snapshot.branch,
        "problem": brief_from_problem(snapshot.selected_problem).model_dump(mode="json"),
        "evidence_tiers": [source.evidence_tier.value for source in snapshot.selected_problem.evidence],
        "design": FYPDesign.model_validate(snapshot.fyp_design.model_dump()).model_dump(mode="json"),
        "definition": ProjectDefinition.model_validate(snapshot.project_definition.model_dump()).model_dump(mode="json"),
        "strategy": AIStrategy.model_validate(snapshot.ai_strategy.strategy).model_dump(mode="json"),
        "dataset": snapshot.dataset_plan.selected_option.model_dump(mode="json"),
        "models": snapshot.model_plan.plan.model_dump(mode="json"),
        "technology": snapshot.technology_plan.plan.model_dump(mode="json"),
        "technical": snapshot.technical_plan.plan.model_dump(mode="json"),
        "report": report.report.model_dump(mode="json") if report else None,
        "report_id": report.id if report else None,
        "report_output": None,
        "accepted_report_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """Make sure the workflow waits inside feasibility_review with the Brain's report; rebuild it if not."""
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == FEASIBILITY_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if waiting and state.values.get("report_id") == values["report_id"] and state.values.get("report") == values["report"]:
        return False
    await graph.aupdate_state(config, values, as_node=ASSESS_FEASIBILITY_NODE)
    await graph.ainvoke(None, config=config)
    return True
