"""
Supervisor readiness events — the brief's progress and result as GreyEvents.
Checklist: checks → talking points → reviewing → saving; then
supervisor_readiness_ready (or supervisor_brief_failed); later supervisor_ready_confirmed.
"""
from app.core.brain.schemas import WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.prepare_supervisor_brief import BriefPhase, BriefProgress
from app.domains.fyp.skills.prepare_supervisor_brief.skill import CHECKING_LABEL, REVIEWING_LABEL, WRITING_LABEL
from app.domains.fyp.workflows.supervisor_readiness.view import SupervisorBriefView

WORKFLOW = "supervisor_readiness"
SAVING_STEP = "saving_brief"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish your supervisor brief right now. Your feasibility report is safe — please try again."
)

_STEPS = [
    (BriefPhase.CHECKING.value, CHECKING_LABEL),
    (BriefPhase.WRITING.value, WRITING_LABEL),
    (BriefPhase.REVIEWING.value, REVIEWING_LABEL),
    (SAVING_STEP, SAVING_LABEL),
]


def _steps(current: str | None, current_done: bool) -> list[dict]:
    ids = [step_id for step_id, _ in _STEPS]
    position = ids.index(current) if current in ids else -1
    return [
        {
            "id": step_id,
            "label": label,
            "state": "done" if index < position or (index == position and current_done)
            else "active" if index == position else "pending",
        }
        for index, (step_id, label) in enumerate(_STEPS)
    ]


def _view_patch(view: SupervisorBriefView) -> dict:
    brief = view.brief
    if brief is None:
        return {}
    return {
        "supervisor_brief_id": brief.id,
        "supervisor_brief_status": brief.status.value,
        "supervisor_attention_count": view.attention_count,
    }


class SupervisorBriefEventBuilder:
    """Builds the events for one supervisor brief attempt."""

    def __init__(self, workspace_id: str, industry: str, branch: str):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch

    def _event(self, type, label, steps, *, stage=WorkflowState.FEASIBILITY_ACCEPTED, status=EventStatus.RUNNING,
               allowed_actions=None, brain_patch=None, **extra) -> GreyEvent:
        return build_event(
            type=type,
            workspace_id=self.workspace_id,
            workflow=WORKFLOW,
            stage=stage.value,
            status=status,
            data={
                "industry": self.industry,
                "branch": self.branch,
                "label": label,
                "steps": steps,
                "completed_steps": sum(1 for s in steps if s["state"] == "done"),
                "total_steps": len(steps),
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        return self._event(EventType.SUPERVISOR_BRIEF_STARTED, "Preparing you for your supervisor",
                           _steps(None, False), brain_patch={"supervisor_brief_status": "running"})

    def progress(self, progress: BriefProgress) -> GreyEvent:
        steps = _steps(progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.SUPERVISOR_BRIEF_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.SUPERVISOR_BRIEF_PROGRESS, SAVING_LABEL, _steps(SAVING_STEP, False))

    def ready(self, view: SupervisorBriefView) -> GreyEvent:
        return self._event(
            EventType.SUPERVISOR_READINESS_READY,
            "Your supervisor brief is ready",
            _steps(SAVING_STEP, True),
            stage=WorkflowState.SUPERVISOR_READINESS,
            status=EventStatus.AWAITING_USER,
            allowed_actions=[AllowedAction.CONFIRM_SUPERVISOR_READY],
            brain_patch={"workflow_state": WorkflowState.SUPERVISOR_READINESS.value, **_view_patch(view)},
            supervisor_brief=view.model_dump(mode="json"),
        )

    def failed(self) -> GreyEvent:
        return self._event(
            EventType.SUPERVISOR_BRIEF_FAILED,
            "Grey couldn't finish your supervisor brief",
            _steps(None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.PREPARE_SUPERVISOR_BRIEF],
            brain_patch={"supervisor_brief_status": "failed"},
            message=FAILED_MESSAGE,
        )


def supervisor_ready_event(workspace_id: str, view: SupervisorBriefView) -> GreyEvent:
    """The student confirmed they're ready for the supervisor. Next, Grey writes the proposal (Release 0.14)."""
    return build_event(
        type=EventType.SUPERVISOR_READY_CONFIRMED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.SUPERVISOR_READY.value,
        status=EventStatus.COMPLETE,
        data={"supervisor_brief": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.SUPERVISOR_READY.value, **_view_patch(view)},
        allowed_actions=[AllowedAction.GENERATE_PROPOSAL],
    )
