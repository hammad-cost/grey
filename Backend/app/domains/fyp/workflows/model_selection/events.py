"""
Model events — turns the model search's progress and results into GreyEvents.

While Grey works, the student sees a short checklist (searching, choosing,
checking, saving), then the plan to approve (models_ready) or a calm failure
message (model_search_failed); later the approval (models_approved).
Only safe content is sent: step labels and the checked, saved results.
"""
from app.core.brain.schemas import ModelPlanStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.find_models import ModelPhase, ModelProgress
from app.domains.fyp.skills.find_models.skill import CHECKING_LABEL, CHOOSING_LABEL, SEARCHING_LABEL
from app.domains.fyp.workflows.model_selection.view import ModelView

WORKFLOW = "model_selection"
SAVING_STEP = "saving_models"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish looking for models right now. Your selected dataset is safe — please try again."
)
RESEARCH_FAILED_MESSAGE = (
    "Grey couldn't search again right now. Your current model plan is kept, and the new search wasn't used up."
)


def _steps(current: str | None, current_done: bool, first_label: str = SEARCHING_LABEL) -> list[dict]:
    steps_list = [
        (ModelPhase.SEARCHING.value, first_label),
        (ModelPhase.CHOOSING.value, CHOOSING_LABEL),
        (ModelPhase.CHECKING.value, CHECKING_LABEL),
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


def review_actions(view: ModelView) -> list[AllowedAction]:
    actions = [AllowedAction.APPROVE_MODELS]
    if view.available_researches:
        actions.append(AllowedAction.REQUEST_OTHER_MODELS)
    return actions


def _view_patch(view: ModelView) -> dict:
    plan = view.plan
    if plan is None:
        return {}
    return {
        "model_plan_id": plan.id,
        "model_status": plan.status.value,
        "model_option_count": len(plan.plan.options),
        "model_researches_left": view.researches_left,
    }


class ModelEventBuilder:
    """Builds the events for one model search (the first one or a re-search)."""

    def __init__(self, workspace_id: str, industry: str, branch: str, *, research: bool):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.research = research
        self.first_label = SEARCHING_LABEL
        self.working_stage = WorkflowState.MODEL_SELECTION if research else WorkflowState.DATASET_SELECTED

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
                "research": self.research,
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        label = "Looking for other models" if self.research else "Looking for models and APIs for your project"
        return self._event(EventType.MODEL_SEARCH_STARTED, label, _steps(None, False, self.first_label),
                           brain_patch={"model_status": "running"})

    def progress(self, progress: ModelProgress) -> GreyEvent:
        if progress.phase == ModelPhase.SEARCHING:
            self.first_label = progress.label          # "Checking your AI strategy" for a project without AI
        steps = _steps(progress.phase.value, False, self.first_label)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.MODEL_SEARCH_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.MODEL_SEARCH_PROGRESS, SAVING_LABEL, _steps(SAVING_STEP, False, self.first_label))

    def ready(self, view: ModelView) -> GreyEvent:
        return self._event(
            EventType.MODELS_READY,
            "Your model plan is ready",
            _steps(SAVING_STEP, True, self.first_label),
            stage=WorkflowState.MODEL_SELECTION,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.MODEL_SELECTION.value, **_view_patch(view)},
            models=view.model_dump(mode="json"),
        )

    def failed(self, view: ModelView | None) -> GreyEvent:
        """A safe failure event. A failed re-search keeps the current plan, so the review goes on."""
        if view is not None and view.plan is not None and view.plan.status == ModelPlanStatus.DRAFT:
            return self._event(
                EventType.MODEL_SEARCH_FAILED,
                "Grey couldn't search again",
                _steps(None, False, self.first_label),
                stage=WorkflowState.MODEL_SELECTION,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"model_status": "draft", **_view_patch(view)},
                models=view.model_dump(mode="json"),
                message=RESEARCH_FAILED_MESSAGE,
            )
        return self._event(
            EventType.MODEL_SEARCH_FAILED,
            "Grey couldn't finish looking for models",
            _steps(None, False, self.first_label),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.FIND_MODELS],
            brain_patch={"model_status": "failed"},
            message=FAILED_MESSAGE,
        )


def models_approved_event(workspace_id: str, view: ModelView) -> GreyEvent:
    """The student approved the model plan. Release 0.9 ends here."""
    return build_event(
        type=EventType.MODELS_APPROVED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.MODELS_APPROVED.value,
        status=EventStatus.COMPLETE,
        data={"models": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.MODELS_APPROVED.value, **_view_patch(view)},
        allowed_actions=[],
    )
