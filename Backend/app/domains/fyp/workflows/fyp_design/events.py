"""
FYP design events — turns design progress and results into GreyEvents.

While Grey works, the student sees a short checklist:

    ✓ Finding where your project fits
    ● Designing a student-sized FYP          (or "Redesigning your FYP")
    ○ Checking the design against your problem
    ○ Saving your FYP design to your Project Brain

then the area (area_classified), the design to review (fyp_direction_ready),
or a calm failure message (fyp_design_failed); and later the approval
(fyp_direction_approved).

Only safe content is sent: step labels and the checked, saved results.
Never prompts, model reasoning or raw error messages.
"""
from app.core.brain.schemas import FYPDesignRunKind, StoredFunctionalArea, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.classify_area.skill import LABEL as AREA_LABEL
from app.domains.fyp.skills.design_fyp.skill import CHECKING_LABEL, DESIGNING_LABEL, REDESIGNING_LABEL
from app.domains.fyp.skills.fyp_design_shared import DesignPhase, DesignProgress
from app.domains.fyp.workflows.fyp_design.view import FYPDesignView

WORKFLOW = "fyp_design"
SAVING_STEP = "saving_design"
SAVING_LABEL = "Saving your FYP design to your Project Brain"

# (step id, label) in the order the student sees them.
INITIAL_STEPS: list[tuple[str, str]] = [
    (DesignPhase.CLASSIFYING_AREA.value, AREA_LABEL),
    (DesignPhase.DESIGNING_FYP.value, DESIGNING_LABEL),
    (DesignPhase.CHECKING_DESIGN.value, CHECKING_LABEL),
    (SAVING_STEP, SAVING_LABEL),
]
REDESIGN_STEPS: list[tuple[str, str]] = [
    (DesignPhase.DESIGNING_FYP.value, REDESIGNING_LABEL),
    (DesignPhase.CHECKING_DESIGN.value, CHECKING_LABEL),
    (SAVING_STEP, SAVING_LABEL),
]

FAILED_MESSAGE = "Grey couldn't finish designing your FYP right now. Your chosen problem is safe — please try again."
REDESIGN_FAILED_MESSAGE = (
    "Grey couldn't redesign your FYP right now. Your current design is unchanged, and this "
    "attempt didn't use up a redesign."
)


def _steps(plan: list[tuple[str, str]], current: str | None, current_done: bool) -> list[dict]:
    """Steps before `current` are done, `current` is active (or done), the rest are pending."""
    ids = [step_id for step_id, _ in plan]
    position = ids.index(current) if current in ids else -1
    steps = []
    for index, (step_id, label) in enumerate(plan):
        if index < position or (index == position and current_done):
            state = "done"
        elif index == position:
            state = "active"
        else:
            state = "pending"
        steps.append({"id": step_id, "label": label, "state": state})
    return steps


def review_actions(view: FYPDesignView) -> list[AllowedAction]:
    """Approve is always possible while reviewing; adjusting only while redesigns are left."""
    actions = [AllowedAction.APPROVE_FYP_DIRECTION]
    if view.adjustments_left > 0:
        actions.append(AllowedAction.ADJUST_FYP_DIRECTION)
    return actions


def _area_patch(area: StoredFunctionalArea | None) -> dict:
    return {"functional_area": area.functional_area, "specific_area": area.specific_area} if area else {}


def _view_patch(view: FYPDesignView) -> dict:
    patch = _area_patch(view.area)
    if view.design is not None:
        patch.update({
            "fyp_design_id": view.design.id,
            "fyp_title": view.design.title,
            "fyp_design_status": view.design.status.value,
        })
    patch["fyp_adjustments_left"] = view.adjustments_left
    return patch


class FYPDesignEventBuilder:
    """Builds the events for one design (or redesign) run."""

    def __init__(self, workspace_id: str, industry: str, branch: str, kind: FYPDesignRunKind, stage: WorkflowState):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.kind = kind
        self.stage = stage            # the project's stage when the run started
        self.plan = INITIAL_STEPS if kind == FYPDesignRunKind.INITIAL else REDESIGN_STEPS

    def _event(
        self,
        type: EventType,
        label: str,
        steps: list[dict],
        *,
        stage: WorkflowState | None = None,
        status: EventStatus = EventStatus.RUNNING,
        allowed_actions: list[AllowedAction] | None = None,
        brain_patch: dict | None = None,
        **extra,
    ) -> GreyEvent:
        return build_event(
            type=type,
            workspace_id=self.workspace_id,
            workflow=WORKFLOW,
            stage=(stage or self.stage).value,
            status=status,
            data={
                "industry": self.industry,
                "branch": self.branch,
                "kind": self.kind.value,
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
        label = "Turning your problem into an FYP" if self.kind == FYPDesignRunKind.INITIAL else REDESIGNING_LABEL
        return self._event(
            EventType.FYP_DESIGN_STARTED, label, _steps(self.plan, None, False),
            brain_patch={"fyp_design_status": "running"},
        )

    def progress(self, progress: DesignProgress) -> GreyEvent:
        steps = _steps(self.plan, progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.FYP_DESIGN_PROGRESS, label, steps)

    def area_classified(self, area: StoredFunctionalArea) -> GreyEvent:
        """The area is saved (stage AREA_CLASSIFICATION); the design is still coming."""
        self.stage = WorkflowState.AREA_CLASSIFICATION
        return self._event(
            EventType.AREA_CLASSIFIED,
            "Found where your project fits",
            _steps(self.plan, DesignPhase.CLASSIFYING_AREA.value, current_done=True),
            brain_patch={"workflow_state": WorkflowState.AREA_CLASSIFICATION.value, **_area_patch(area)},
            area=area.model_dump(mode="json"),
        )

    def saving(self) -> GreyEvent:
        return self._event(EventType.FYP_DESIGN_PROGRESS, SAVING_LABEL, _steps(self.plan, SAVING_STEP, False))

    def direction_ready(self, view: FYPDesignView) -> GreyEvent:
        """The design to review. The student must approve it or ask for a redesign."""
        return self._event(
            EventType.FYP_DIRECTION_READY,
            "Your FYP design is ready",
            _steps(self.plan, SAVING_STEP, current_done=True),
            stage=WorkflowState.FYP_DESIGN,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.FYP_DESIGN.value, **_view_patch(view)},
            fyp=view.model_dump(mode="json"),
        )

    def failed(self, view: FYPDesignView | None) -> GreyEvent:
        """
        A safe failure event; the real error is stored on the run, not sent.
        A failed first design → "Try again". A failed redesign → the current
        design is still there to approve or adjust.
        """
        if self.kind == FYPDesignRunKind.ADJUSTMENT and view is not None and view.design is not None:
            return self._event(
                EventType.FYP_DESIGN_FAILED,
                "The redesign could not be finished",
                _steps(self.plan, None, False),
                stage=WorkflowState.FYP_DESIGN,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"fyp_design_status": "draft", **_view_patch(view)},
                message=REDESIGN_FAILED_MESSAGE,
                fyp=view.model_dump(mode="json"),
            )
        return self._event(
            EventType.FYP_DESIGN_FAILED,
            "Your FYP could not be designed",
            _steps(self.plan, None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.DESIGN_FYP],
            brain_patch={"fyp_design_status": "failed", **(_area_patch(view.area) if view else {})},
            message=FAILED_MESSAGE,
        )


def fyp_approved_event(workspace_id: str, view: FYPDesignView) -> GreyEvent:
    """The student approved the FYP design. Release 0.5 ends here."""
    return build_event(
        type=EventType.FYP_DIRECTION_APPROVED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.APPROVED_FYP.value,
        status=EventStatus.COMPLETE,
        data={"fyp": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.APPROVED_FYP.value, **_view_patch(view)},
        allowed_actions=[],
    )
