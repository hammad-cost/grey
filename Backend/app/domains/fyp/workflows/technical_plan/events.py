"""
Architecture events — the technical plan's progress and results as GreyEvents.
Checklist: designing → checking → saving; then architecture_ready (or _failed);
later technical_plan_approved. Only safe content is sent.
"""
from app.core.brain.schemas import TechnicalPlanStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.design_architecture import ArchitecturePhase, ArchitectureProgress
from app.domains.fyp.skills.design_architecture.skill import CHECKING_LABEL, DESIGNING_LABEL, REDESIGNING_LABEL
from app.domains.fyp.workflows.technical_plan.view import TechnicalPlanView

WORKFLOW = "technical_plan"
SAVING_STEP = "saving_architecture"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish the architecture right now. Your approved technology plan is safe — please try again."
)
REDESIGN_FAILED_MESSAGE = (
    "Grey couldn't simplify the architecture right now. Your current plan is kept, and the redesign wasn't used up."
)


def _steps(first_label: str, current: str | None, current_done: bool) -> list[dict]:
    steps_list = [
        (ArchitecturePhase.DESIGNING.value, first_label),
        (ArchitecturePhase.CHECKING.value, CHECKING_LABEL),
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


def review_actions(view: TechnicalPlanView) -> list[AllowedAction]:
    actions = [AllowedAction.APPROVE_TECHNICAL_PLAN]
    if view.can_redesign:
        actions.append(AllowedAction.REDESIGN_ARCHITECTURE)
    return actions


def _view_patch(view: TechnicalPlanView) -> dict:
    plan = view.plan
    if plan is None:
        return {}
    return {
        "technical_plan_id": plan.id,
        "technical_plan_status": plan.status.value,
        "architecture_component_count": len(plan.plan.architecture.components),
        "architecture_redesigns_left": view.redesigns_left,
    }


class ArchitectureEventBuilder:
    """Builds the events for one technical plan attempt (the first one or a redesign)."""

    def __init__(self, workspace_id: str, industry: str, branch: str, *, redesign: bool):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.redesign = redesign
        self.first_label = REDESIGNING_LABEL if redesign else DESIGNING_LABEL
        self.working_stage = WorkflowState.ARCHITECTURE if redesign else WorkflowState.TECHNOLOGY_APPROVED

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
                "redesign": self.redesign,
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        label = "Simplifying the architecture" if self.redesign else "Designing your architecture and evaluation plan"
        return self._event(EventType.ARCHITECTURE_STARTED, label, _steps(self.first_label, None, False),
                           brain_patch={"technical_plan_status": "running"})

    def progress(self, progress: ArchitectureProgress) -> GreyEvent:
        steps = _steps(self.first_label, progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.ARCHITECTURE_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.ARCHITECTURE_PROGRESS, SAVING_LABEL, _steps(self.first_label, SAVING_STEP, False))

    def ready(self, view: TechnicalPlanView) -> GreyEvent:
        return self._event(
            EventType.ARCHITECTURE_READY,
            "Your architecture and evaluation plan are ready",
            _steps(self.first_label, SAVING_STEP, True),
            stage=WorkflowState.ARCHITECTURE,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.ARCHITECTURE.value, **_view_patch(view)},
            technical_plan=view.model_dump(mode="json"),
        )

    def failed(self, view: TechnicalPlanView | None) -> GreyEvent:
        if view is not None and view.plan is not None and view.plan.status == TechnicalPlanStatus.DRAFT:
            return self._event(
                EventType.ARCHITECTURE_FAILED,
                "Grey couldn't simplify the architecture",
                _steps(self.first_label, None, False),
                stage=WorkflowState.ARCHITECTURE,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"technical_plan_status": "draft", **_view_patch(view)},
                technical_plan=view.model_dump(mode="json"),
                message=REDESIGN_FAILED_MESSAGE,
            )
        return self._event(
            EventType.ARCHITECTURE_FAILED,
            "Grey couldn't finish the architecture",
            _steps(self.first_label, None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.DESIGN_ARCHITECTURE],
            brain_patch={"technical_plan_status": "failed"},
            message=FAILED_MESSAGE,
        )


def technical_plan_approved_event(workspace_id: str, view: TechnicalPlanView) -> GreyEvent:
    """The student approved the architecture and evaluation plan. Release 0.11 ends here."""
    return build_event(
        type=EventType.TECHNICAL_PLAN_APPROVED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.TECHNICAL_PLAN_APPROVED.value,
        status=EventStatus.COMPLETE,
        data={"technical_plan": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.TECHNICAL_PLAN_APPROVED.value, **_view_patch(view)},
        allowed_actions=[],
    )
