"""
Proposal runner (Release 0.14) — writes the proposal, rewrites a section when
the student asks, and finalizes it (the end of the FYP journey).

    session = await start_proposal(workspace_id, repo, graph)
    session = await start_proposal_rewrite(workspace_id, section, repo, graph)
    async for event in session.events(): ...
    event = await finalize_proposal(workspace_id, proposal_id, repo, graph)
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langgraph.types import Command

from app.core.brain.proposal_rules import rewrite_problem
from app.core.brain.repository import ProposalError, ProposalRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_PROPOSAL_REWRITES,
    Proposal,
    ProposalRun,
    ProposalRunStatus,
    ProposalSectionId,
    ProposalStatus,
    SupervisorBriefStatus,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.events import GreyEvent
from app.domains.fyp.skills.generate_proposal import ProposalProgress
from app.domains.fyp.workflows.discovery.research_runner import ProjectNotFoundError
from app.domains.fyp.workflows.proposal.events import ProposalEventBuilder, proposal_finalized_event
from app.domains.fyp.workflows.proposal.graph import GENERATE_PROPOSAL_NODE, PROPOSAL_REVIEW_NODE
from app.domains.fyp.workflows.proposal.nodes import FINALIZE, PROPOSAL_PROGRESS_KIND, REWRITE
from app.domains.fyp.workflows.proposal.view import build_proposal_view
from app.domains.fyp.workflows.supervisor_readiness import brief_input

INTERRUPTED_ERROR = "Interrupted: the server stopped before the proposal finished."

_active_proposals: set[str] = set()


class ProposalNotAllowedError(ValueError):
    """The project is not at a point where this proposal step is allowed."""


@dataclass
class ProposalSession:
    workspace_id: str
    run: ProposalRun
    _repo: WorkspaceBrainRepository
    _graph: object
    _builder: ProposalEventBuilder
    _graph_input: object

    async def events(self) -> AsyncIterator[GreyEvent]:
        """proposal_started → proposal_progress … → proposal_ready (or proposal_failed). Never raises."""
        config = _config(self.workspace_id)
        try:
            yield self._builder.started()
            update: dict | None = None
            async for mode, chunk in self._graph.astream(self._graph_input, config, stream_mode=["custom", "updates"]):
                if mode == "custom" and chunk.get("kind") == PROPOSAL_PROGRESS_KIND:
                    yield self._builder.progress(ProposalProgress.model_validate(chunk["progress"]))
                elif mode == "updates" and GENERATE_PROPOSAL_NODE in chunk:
                    update = chunk[GENERATE_PROPOSAL_NODE]
            if update is None:
                raise RuntimeError("The proposal workflow finished without a proposal.")
            yield self._builder.saving()
            output = update["proposal_output"]
            await self._repo.complete_proposal_run(
                self.run.id,
                Proposal.model_validate(output["proposal"]),
                proposal_id=update["proposal_id"],
                provider=output["provider"],
                model=output["model"],
                prompt_version=output["prompt_version"],
            )
            self.run = await self._repo.get_latest_proposal_run(self.workspace_id)
            yield self._builder.ready(build_proposal_view(await self._repo.get_snapshot(self.workspace_id)))
        except Exception as error:   # noqa: BLE001 — every failure becomes a safe event
            self.run = await self._repo.fail_proposal_run(self.run.id, f"{type(error).__name__}: {error}")
            yield self._builder.failed(build_proposal_view(await self._repo.get_snapshot(self.workspace_id)))
        finally:
            _active_proposals.discard(self.workspace_id)


async def start_proposal(workspace_id: str, repo: WorkspaceBrainRepository, graph) -> ProposalSession:
    """Check the project and start writing the proposal (or retry). Raises ProjectNotFoundError,
    ProposalNotAllowedError, ProposalRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    brief = snapshot.supervisor_brief
    if (
        snapshot.workflow_state != WorkflowState.SUPERVISOR_READY
        or brief is None
        or brief.status != SupervisorBriefStatus.CONFIRMED
        or snapshot.proposal is not None
    ):
        raise ProposalNotAllowedError(
            f"Grey writes the proposal right after you're ready for your supervisor (stage: {snapshot.workflow_state.value})."
        )
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        run = await repo.start_proposal_run(workspace_id)
    except BaseException:
        _active_proposals.discard(workspace_id)
        raise
    return ProposalSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=ProposalEventBuilder(workspace_id, snapshot.industry, snapshot.branch, rewrite=None),
        _graph_input=_workflow_values(snapshot),
    )


async def start_proposal_rewrite(
    workspace_id: str, section: ProposalSectionId, repo: WorkspaceBrainRepository, graph
) -> ProposalSession:
    """Check the project and start rewriting one section. Raises ProjectNotFoundError,
    ProposalNotAllowedError, ProposalRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    proposal = _require_draft(snapshot)
    if proposal.rewrites_used >= MAX_PROPOSAL_REWRITES:
        raise ProposalNotAllowedError(
            f"All {MAX_PROPOSAL_REWRITES} rewrites have been used. You can finalize the proposal."
        )
    problem = rewrite_problem(section)
    if problem is not None:
        raise ProposalNotAllowedError(problem)
    _claim(workspace_id)
    try:
        await _fail_leftover_run(repo, snapshot)
        await _position_at_review(graph, snapshot)
        run = await repo.start_proposal_run(workspace_id, section)
    except ProposalError as error:
        _active_proposals.discard(workspace_id)
        raise ProposalNotAllowedError(str(error)) from error
    except BaseException:
        _active_proposals.discard(workspace_id)
        raise
    return ProposalSession(
        workspace_id=workspace_id, run=run, _repo=repo, _graph=graph,
        _builder=ProposalEventBuilder(workspace_id, snapshot.industry, snapshot.branch, rewrite=section.value),
        _graph_input=Command(resume={"action": REWRITE, "section": section.value}),
    )


async def finalize_proposal(workspace_id: str, proposal_id: str, repo: WorkspaceBrainRepository, graph) -> GreyEvent:
    """Apply the student's finalization (HITL resume). Raises ProjectNotFoundError,
    ProposalNotAllowedError, ProposalRunAlreadyRunningError."""
    snapshot = await _require_snapshot(repo, workspace_id)
    proposal = _require_draft(snapshot)
    if proposal.id != proposal_id:
        raise ProposalNotAllowedError(f"'{proposal_id}' is not this project's proposal.")
    if workspace_id in _active_proposals:
        raise ProposalRunAlreadyRunningError(f"A rewrite is running for '{workspace_id}'.")
    await _position_at_review(graph, snapshot)
    await graph.ainvoke(Command(resume={"action": FINALIZE, "proposal_id": proposal_id}), config=_config(workspace_id))
    await repo.finalize_proposal(workspace_id, proposal_id)
    return proposal_finalized_event(workspace_id, build_proposal_view(await repo.get_snapshot(workspace_id)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(workspace_id: str) -> dict:
    return {"configurable": {"thread_id": workspace_id}}


async def _require_snapshot(repo: WorkspaceBrainRepository, workspace_id: str) -> WorkspaceBrainSnapshot:
    snapshot = await repo.get_snapshot(workspace_id)
    if snapshot is None:
        raise ProjectNotFoundError(f"Project '{workspace_id}' not found.")
    return snapshot


def _require_draft(snapshot: WorkspaceBrainSnapshot):
    proposal = snapshot.proposal
    if (
        snapshot.workflow_state != WorkflowState.PROPOSAL_GENERATION
        or proposal is None
        or proposal.status != ProposalStatus.DRAFT
    ):
        raise ProposalNotAllowedError(f"There is no proposal to review right now (stage: {snapshot.workflow_state.value}).")
    return proposal


def _claim(workspace_id: str) -> None:
    if workspace_id in _active_proposals:
        raise ProposalRunAlreadyRunningError(f"A proposal is already being written for '{workspace_id}'.")
    _active_proposals.add(workspace_id)


async def _fail_leftover_run(repo: WorkspaceBrainRepository, snapshot: WorkspaceBrainSnapshot) -> None:
    run = snapshot.proposal_run
    if run is not None and run.status == ProposalRunStatus.RUNNING:
        await repo.fail_proposal_run(run.id, INTERRUPTED_ERROR)


def _workflow_values(snapshot: WorkspaceBrainSnapshot) -> dict:
    proposal = snapshot.proposal
    return {
        "workspace_id": snapshot.workspace_id,
        "workflow_state": snapshot.workflow_state.value,
        "inputs": brief_input(snapshot).model_dump(mode="json"),
        "proposal": proposal.proposal.model_dump(mode="json") if proposal else None,
        "proposal_id": proposal.id if proposal else None,
        "proposal_output": None,
        "rewrites_used": proposal.rewrites_used if proposal else 0,
        "rewrite_section": None,
        "finalized_id": None,
    }


async def _position_at_review(graph, snapshot: WorkspaceBrainSnapshot) -> bool:
    """Make sure the workflow waits inside proposal_review with the Brain's proposal; rebuild it if not."""
    config = _config(snapshot.workspace_id)
    state = await graph.aget_state(config)
    values = _workflow_values(snapshot)
    waiting = bool(state.tasks) and state.tasks[0].name == PROPOSAL_REVIEW_NODE and bool(state.tasks[0].interrupts)
    if waiting and all(state.values.get(k) == values[k] for k in ("proposal_id", "rewrites_used", "proposal")):
        return False
    await graph.aupdate_state(config, values, as_node=GENERATE_PROPOSAL_NODE)
    await graph.ainvoke(None, config=config)
    return True
