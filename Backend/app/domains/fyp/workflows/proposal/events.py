"""
Proposal events — the proposal's progress and result as GreyEvents.
Checklist: building → writing (three parts, or one rewritten section) → checking
→ saving; then proposal_ready (or proposal_failed); later proposal_finalized.
"""
from app.core.brain.schemas import ProposalStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.generate_proposal import ProposalPhase, ProposalProgress
from app.domains.fyp.skills.generate_proposal.skill import BUILDING_LABEL, CHECKING_LABEL
from app.domains.fyp.workflows.proposal.view import ProposalView

WORKFLOW = "proposal"
SAVING_STEP = "saving_proposal"
SAVING_LABEL = "Saving it to your Project Brain"
WRITING_LABEL = "Writing the narrative sections"

FAILED_MESSAGE = (
    "Grey couldn't finish your proposal right now. Your supervisor brief is safe — please try again."
)
REWRITE_FAILED_MESSAGE = (
    "Grey couldn't rewrite that section right now. Your proposal is kept, and the rewrite wasn't used up."
)


def _steps(writing_label: str, current: str | None, current_done: bool) -> list[dict]:
    steps_list = [
        (ProposalPhase.BUILDING.value, BUILDING_LABEL),
        (ProposalPhase.WRITING.value, writing_label),
        (ProposalPhase.CHECKING.value, CHECKING_LABEL),
        (SAVING_STEP, SAVING_LABEL),
    ]
    ids = [step_id for step_id, _ in steps_list]
    position = ids.index(current) if current in ids else -1
    return [
        {
            "id": step_id,
            "label": label,
            "state": "done" if index < position or (index == position and current_done)
            else "active" if index == position else "pending",
        }
        for index, (step_id, label) in enumerate(steps_list)
    ]


def review_actions(view: ProposalView) -> list[AllowedAction]:
    actions = [AllowedAction.FINALIZE_PROPOSAL]
    if view.rewritable_sections:
        actions.append(AllowedAction.REWRITE_PROPOSAL_SECTION)
    return actions


def _view_patch(view: ProposalView) -> dict:
    proposal = view.proposal
    if proposal is None:
        return {}
    return {
        "proposal_id": proposal.id,
        "proposal_status": proposal.status.value,
        "proposal_rewrites_left": view.rewrites_left,
    }


class ProposalEventBuilder:
    """Builds the events for one proposal attempt (the whole proposal or one rewrite)."""

    def __init__(self, workspace_id: str, industry: str, branch: str, *, rewrite: str | None):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.rewrite = rewrite
        self.writing_label = WRITING_LABEL
        self.working_stage = WorkflowState.PROPOSAL_GENERATION if rewrite else WorkflowState.SUPERVISOR_READY

    def _event(self, type, label, steps, *, stage=None, status=EventStatus.RUNNING,
               allowed_actions=None, brain_patch=None, **extra) -> GreyEvent:
        return build_event(
            type=type,
            workspace_id=self.workspace_id,
            workflow=WORKFLOW,
            stage=(stage or self.working_stage).value,
            status=status,
            data={
                "industry": self.industry,
                "branch": self.branch,
                "label": label,
                "steps": steps,
                "completed_steps": sum(1 for s in steps if s["state"] == "done"),
                "total_steps": len(steps),
                "rewrite": self.rewrite,
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        label = "Rewriting a section of your proposal" if self.rewrite else "Writing your proposal"
        return self._event(EventType.PROPOSAL_STARTED, label, _steps(self.writing_label, None, False),
                           brain_patch={"proposal_status": "running"})

    def progress(self, progress: ProposalProgress) -> GreyEvent:
        if progress.phase == ProposalPhase.WRITING:
            self.writing_label = progress.label        # one of GROUP_LABELS, or "Rewriting <section>"
        steps = _steps(self.writing_label, progress.phase.value, False)
        return self._event(EventType.PROPOSAL_PROGRESS, progress.label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.PROPOSAL_PROGRESS, SAVING_LABEL, _steps(self.writing_label, SAVING_STEP, False))

    def ready(self, view: ProposalView) -> GreyEvent:
        return self._event(
            EventType.PROPOSAL_READY,
            "Your proposal is ready",
            _steps(WRITING_LABEL, SAVING_STEP, True),
            stage=WorkflowState.PROPOSAL_GENERATION,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.PROPOSAL_GENERATION.value, **_view_patch(view)},
            proposal=view.model_dump(mode="json"),
        )

    def failed(self, view: ProposalView | None) -> GreyEvent:
        if view is not None and view.proposal is not None and view.proposal.status == ProposalStatus.DRAFT:
            return self._event(
                EventType.PROPOSAL_FAILED,
                "Grey couldn't rewrite that section",
                _steps(self.writing_label, None, False),
                stage=WorkflowState.PROPOSAL_GENERATION,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"proposal_status": "draft", **_view_patch(view)},
                proposal=view.model_dump(mode="json"),
                message=REWRITE_FAILED_MESSAGE,
            )
        return self._event(
            EventType.PROPOSAL_FAILED,
            "Grey couldn't finish your proposal",
            _steps(self.writing_label, None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.GENERATE_PROPOSAL],
            brain_patch={"proposal_status": "failed"},
            message=FAILED_MESSAGE,
        )


def proposal_finalized_event(workspace_id: str, view: ProposalView) -> GreyEvent:
    """The student finalized the proposal. The FYP journey is complete (Release 0.14)."""
    return build_event(
        type=EventType.PROPOSAL_FINALIZED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.COMPLETE.value,
        status=EventStatus.COMPLETE,
        data={"proposal": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.COMPLETE.value, **_view_patch(view)},
        allowed_actions=[],
    )
