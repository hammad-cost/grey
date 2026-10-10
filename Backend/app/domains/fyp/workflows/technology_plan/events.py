"""
Technology events — the plan's progress and results as GreyEvents.
Checklist: planning → checking → saving; then technology_plan_ready (or _failed);
later technology_approved. Only safe content is sent.
"""
from app.core.brain.schemas import TechnologyPlanStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.plan_technology import TechnologyPhase, TechnologyProgress
from app.domains.fyp.skills.plan_technology.skill import CHECKING_LABEL, PLANNING_LABEL, REPLANNING_LABEL
from app.domains.fyp.workflows.technology_plan.view import TechnologyView

WORKFLOW = "technology_plan"
SAVING_STEP = "saving_technology"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish the technology plan right now. Your approved model plan is safe — please try again."
)
REPLAN_FAILED_MESSAGE = (
    "Grey couldn't make a simpler plan right now. Your current plan is kept, and the re-plan wasn't used up."
)


def _steps(first_label: str, current: str | None, current_done: bool) -> list[dict]:
    steps_list = [
        (TechnologyPhase.PLANNING.value, first_label),
        (TechnologyPhase.CHECKING.value, CHECKING_LABEL),
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


def review_actions(view: TechnologyView) -> list[AllowedAction]:
    actions = [AllowedAction.APPROVE_TECHNOLOGY]
    if view.can_replan:
        actions.append(AllowedAction.REPLAN_TECHNOLOGY)
    return actions


def _view_patch(view: TechnologyView) -> dict:
    plan = view.plan
    if plan is None:
        return {}
    return {
        "technology_plan_id": plan.id,
        "technology_status": plan.status.value,
        "technology_replans_left": view.replans_left,
    }


class TechnologyEventBuilder:
    """Builds the events for one technology plan attempt (the first one or a re-plan)."""

    def __init__(self, workspace_id: str, industry: str, branch: str, *, replan: bool):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.replan = replan
        self.first_label = REPLANNING_LABEL if replan else PLANNING_LABEL
        self.working_stage = WorkflowState.TECHNOLOGY_PLAN if replan else WorkflowState.MODELS_APPROVED

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
                "replan": self.replan,
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        label = "Making the plan simpler" if self.replan else "Planning your technology and hardware"
        return self._event(EventType.TECHNOLOGY_PLAN_STARTED, label, _steps(self.first_label, None, False),
                           brain_patch={"technology_status": "running"})

    def progress(self, progress: TechnologyProgress) -> GreyEvent:
        steps = _steps(self.first_label, progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.TECHNOLOGY_PLAN_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.TECHNOLOGY_PLAN_PROGRESS, SAVING_LABEL, _steps(self.first_label, SAVING_STEP, False))

    def ready(self, view: TechnologyView) -> GreyEvent:
        return self._event(
            EventType.TECHNOLOGY_PLAN_READY,
            "Your technology plan is ready",
            _steps(self.first_label, SAVING_STEP, True),
            stage=WorkflowState.TECHNOLOGY_PLAN,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.TECHNOLOGY_PLAN.value, **_view_patch(view)},
            technology=view.model_dump(mode="json"),
        )

    def failed(self, view: TechnologyView | None) -> GreyEvent:
        if view is not None and view.plan is not None and view.plan.status == TechnologyPlanStatus.DRAFT:
            return self._event(
                EventType.TECHNOLOGY_PLAN_FAILED,
                "Grey couldn't make a simpler plan",
                _steps(self.first_label, None, False),
                stage=WorkflowState.TECHNOLOGY_PLAN,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"technology_status": "draft", **_view_patch(view)},
                technology=view.model_dump(mode="json"),
                message=REPLAN_FAILED_MESSAGE,
            )
        return self._event(
            EventType.TECHNOLOGY_PLAN_FAILED,
            "Grey couldn't finish the technology plan",
            _steps(self.first_label, None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.PLAN_TECHNOLOGY],
            brain_patch={"technology_status": "failed"},
            message=FAILED_MESSAGE,
        )


def technology_approved_event(workspace_id: str, view: TechnologyView) -> GreyEvent:
    """The student approved the technology plan. Next, Grey designs the architecture (Release 0.11)."""
    return build_event(
        type=EventType.TECHNOLOGY_APPROVED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.TECHNOLOGY_APPROVED.value,
        status=EventStatus.COMPLETE,
        data={"technology": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.TECHNOLOGY_APPROVED.value, **_view_patch(view)},
        allowed_actions=[AllowedAction.DESIGN_ARCHITECTURE],
    )
