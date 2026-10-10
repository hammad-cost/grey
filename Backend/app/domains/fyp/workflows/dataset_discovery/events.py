"""
Dataset events — turns the dataset search's progress and results into GreyEvents.

While Grey works, the student sees a short checklist:

    ✓ Searching dataset sites
    ● Choosing the two best options for your project
    ○ Checking each dataset really fits your problem
    ○ Saving it to your Project Brain

then the two datasets to choose from (dataset_options_ready) or a calm failure
message (dataset_search_failed); later the selection (dataset_selected).

Only safe content is sent: step labels and the checked, saved results.
Never prompts, model reasoning or raw error messages.
"""
from app.core.brain.schemas import DatasetPlanStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.find_datasets import DatasetPhase, DatasetProgress
from app.domains.fyp.skills.find_datasets.skill import CHECKING_LABEL, CHOOSING_LABEL, SEARCHING_LABEL
from app.domains.fyp.workflows.dataset_discovery.view import DatasetView

WORKFLOW = "dataset_discovery"
SAVING_STEP = "saving_datasets"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish looking for datasets right now. "
    "Your approved AI strategy is safe — please try again."
)
RESEARCH_FAILED_MESSAGE = (
    "Grey couldn't search again right now. Your current datasets are kept, and the new search wasn't used up."
)


def _steps(current: str | None, current_done: bool, first_label: str = SEARCHING_LABEL) -> list[dict]:
    """Steps before `current` are done, `current` is active (or done), the rest are pending."""
    steps_list = [
        (DatasetPhase.SEARCHING.value, first_label),
        (DatasetPhase.CHOOSING.value, CHOOSING_LABEL),
        (DatasetPhase.CHECKING.value, CHECKING_LABEL),
        (SAVING_STEP, SAVING_LABEL),
    ]
    ids = [step_id for step_id, _ in steps_list]
    position = ids.index(current) if current in ids else -1
    steps = []
    for index, (step_id, label) in enumerate(steps_list):
        if index < position or (index == position and current_done):
            state = "done"
        elif index == position:
            state = "active"
        else:
            state = "pending"
        steps.append({"id": step_id, "label": label, "state": state})
    return steps


def review_actions(view: DatasetView) -> list[AllowedAction]:
    """While reviewing: select, and search again only when a re-search is still possible."""
    actions = [AllowedAction.SELECT_DATASET]
    if view.available_researches:
        actions.append(AllowedAction.REQUEST_DATASET_ALTERNATIVE)
    return actions


def _view_patch(view: DatasetView) -> dict:
    plan = view.plan
    if plan is None:
        return {}
    patch = {
        "dataset_plan_id": plan.id,
        "dataset_status": plan.status.value,
        "dataset_researches_left": view.researches_left,
    }
    if plan.selected_option is not None:
        patch["dataset_selected"] = plan.selected_option.name
    return patch


class DatasetEventBuilder:
    """Builds the events for one dataset search (the first one or a re-search)."""

    def __init__(self, workspace_id: str, industry: str, branch: str, *, research: bool):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.research = research
        self.first_label = SEARCHING_LABEL
        # Where the project is while Grey works: a re-search happens during the review.
        self.working_stage = WorkflowState.DATASET_DISCOVERY if research else WorkflowState.AI_STRATEGY_APPROVED

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
        label = "Searching again with your preference" if self.research else "Looking for datasets for your project"
        return self._event(
            EventType.DATASET_SEARCH_STARTED, label, _steps(None, False, self.first_label),
            brain_patch={"dataset_status": "running"},
        )

    def progress(self, progress: DatasetProgress) -> GreyEvent:
        if progress.phase == DatasetPhase.SEARCHING:
            self.first_label = progress.label          # "Looking at the datasets found before" for own data
        steps = _steps(progress.phase.value, False, self.first_label)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.DATASET_SEARCH_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(
            EventType.DATASET_SEARCH_PROGRESS, SAVING_LABEL, _steps(SAVING_STEP, False, self.first_label)
        )

    def ready(self, view: DatasetView) -> GreyEvent:
        """The two datasets to choose from. The student may search again, then must select one."""
        return self._event(
            EventType.DATASET_OPTIONS_READY,
            "Your dataset options are ready",
            _steps(SAVING_STEP, True, self.first_label),
            stage=WorkflowState.DATASET_DISCOVERY,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.DATASET_DISCOVERY.value, **_view_patch(view)},
            datasets=view.model_dump(mode="json"),
        )

    def failed(self, view: DatasetView | None) -> GreyEvent:
        """
        A safe failure event; the real error is stored on the run, not sent.
        A failed re-search keeps the current datasets, so the review goes on.
        """
        draft = view is not None and view.plan is not None and view.plan.status == DatasetPlanStatus.DRAFT
        if draft:
            return self._event(
                EventType.DATASET_SEARCH_FAILED,
                "Grey couldn't search again",
                _steps(None, False, self.first_label),
                stage=WorkflowState.DATASET_DISCOVERY,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"dataset_status": "draft", **_view_patch(view)},
                datasets=view.model_dump(mode="json"),
                message=RESEARCH_FAILED_MESSAGE,
            )
        return self._event(
            EventType.DATASET_SEARCH_FAILED,
            "Grey couldn't finish looking for datasets",
            _steps(None, False, self.first_label),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.FIND_DATASETS],
            brain_patch={"dataset_status": "failed"},
            message=FAILED_MESSAGE,
        )


def dataset_selected_event(workspace_id: str, view: DatasetView) -> GreyEvent:
    """The student selected a dataset. Release 0.8 ends here."""
    return build_event(
        type=EventType.DATASET_SELECTED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.DATASET_SELECTED.value,
        status=EventStatus.COMPLETE,
        data={"datasets": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.DATASET_SELECTED.value, **_view_patch(view)},
        allowed_actions=[],
    )
