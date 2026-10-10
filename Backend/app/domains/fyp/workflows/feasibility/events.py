"""
Feasibility events — the analysis' progress and result as GreyEvents.
Checklist: facts → judging → computing → saving; then feasibility_ready (or
feasibility_failed); later feasibility_accepted. Only safe content is sent.
"""
from app.core.brain.schemas import WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.assess_feasibility import FeasibilityPhase, FeasibilityProgress
from app.domains.fyp.skills.assess_feasibility.skill import CHECKING_LABEL, FACTS_LABEL, JUDGING_LABEL
from app.domains.fyp.workflows.feasibility.view import FeasibilityView

WORKFLOW = "feasibility"
SAVING_STEP = "saving_feasibility"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish the feasibility check right now. Your approved technical plan is safe — please try again."
)

_STEPS = [
    (FeasibilityPhase.FACTS.value, FACTS_LABEL),
    (FeasibilityPhase.JUDGING.value, JUDGING_LABEL),
    (FeasibilityPhase.CHECKING.value, CHECKING_LABEL),
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


def _view_patch(view: FeasibilityView) -> dict:
    report = view.report
    if report is None:
        return {}
    return {
        "feasibility_report_id": report.id,
        "feasibility_status": report.status.value,
        "feasibility_overall": report.report.overall.value,
    }


class FeasibilityEventBuilder:
    """Builds the events for one feasibility analysis."""

    def __init__(self, workspace_id: str, industry: str, branch: str):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch

    def _event(self, type, label, steps, *, stage=WorkflowState.TECHNICAL_PLAN_APPROVED, status=EventStatus.RUNNING,
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
        return self._event(EventType.FEASIBILITY_STARTED, "Checking whether your project is feasible",
                           _steps(None, False), brain_patch={"feasibility_status": "running"})

    def progress(self, progress: FeasibilityProgress) -> GreyEvent:
        steps = _steps(progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.FEASIBILITY_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.FEASIBILITY_PROGRESS, SAVING_LABEL, _steps(SAVING_STEP, False))

    def ready(self, view: FeasibilityView) -> GreyEvent:
        return self._event(
            EventType.FEASIBILITY_READY,
            "Your feasibility report is ready",
            _steps(SAVING_STEP, True),
            stage=WorkflowState.FEASIBILITY,
            status=EventStatus.AWAITING_USER,
            allowed_actions=[AllowedAction.ACCEPT_FEASIBILITY],
            brain_patch={"workflow_state": WorkflowState.FEASIBILITY.value, **_view_patch(view)},
            feasibility=view.model_dump(mode="json"),
        )

    def failed(self) -> GreyEvent:
        return self._event(
            EventType.FEASIBILITY_FAILED,
            "Grey couldn't finish the feasibility check",
            _steps(None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.ASSESS_FEASIBILITY],
            brain_patch={"feasibility_status": "failed"},
            message=FAILED_MESSAGE,
        )


def feasibility_accepted_event(workspace_id: str, view: FeasibilityView) -> GreyEvent:
    """The student accepted the feasibility report. Release 0.12 ends here."""
    return build_event(
        type=EventType.FEASIBILITY_ACCEPTED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.FEASIBILITY_ACCEPTED.value,
        status=EventStatus.COMPLETE,
        data={"feasibility": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.FEASIBILITY_ACCEPTED.value, **_view_patch(view)},
        allowed_actions=[],
    )
