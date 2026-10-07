"""
Project definition events — turns definition progress and results into GreyEvents.

While Grey works, the student sees a short checklist:

    ✓ Writing your problem definition, scope and solution
    ● Checking the definition against your FYP
    ○ Saving it to your Project Brain

then the definition to review (project_definition_ready) or a calm failure
message (project_definition_failed); later each scope change (scope_updated)
and the approval (scope_approved).

Only safe content is sent: step labels and the checked, saved results.
Never prompts, model reasoning or raw error messages.
"""
from app.core.brain.schemas import ScopeKind, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.define_project import DefinitionPhase, DefinitionProgress
from app.domains.fyp.skills.define_project.skill import CHECKING_LABEL, DEFINING_LABEL
from app.domains.fyp.workflows.project_definition.view import ProjectDefinitionView

WORKFLOW = "project_definition"
SAVING_STEP = "saving_definition"
SAVING_LABEL = "Saving it to your Project Brain"

# (step id, label) in the order the student sees them.
STEPS: list[tuple[str, str]] = [
    (DefinitionPhase.DEFINING_PROJECT.value, DEFINING_LABEL),
    (DefinitionPhase.CHECKING_DEFINITION.value, CHECKING_LABEL),
    (SAVING_STEP, SAVING_LABEL),
]

FAILED_MESSAGE = (
    "Grey couldn't finish defining your project right now. Your approved FYP is safe — please try again."
)

REVIEW_ACTIONS = [AllowedAction.APPROVE_SCOPE, AllowedAction.MODIFY_SCOPE]


def _steps(current: str | None, current_done: bool) -> list[dict]:
    """Steps before `current` are done, `current` is active (or done), the rest are pending."""
    ids = [step_id for step_id, _ in STEPS]
    position = ids.index(current) if current in ids else -1
    steps = []
    for index, (step_id, label) in enumerate(STEPS):
        if index < position or (index == position and current_done):
            state = "done"
        elif index == position:
            state = "active"
        else:
            state = "pending"
        steps.append({"id": step_id, "label": label, "state": state})
    return steps


def _view_patch(view: ProjectDefinitionView) -> dict:
    definition = view.definition
    if definition is None:
        return {}
    return {
        "project_definition_id": definition.id,
        "project_definition_status": definition.status.value,
        "core_feature_count": sum(1 for item in definition.scope if item.kind == ScopeKind.CORE),
    }


class ProjectDefinitionEventBuilder:
    """Builds the events for one attempt at writing the project definition."""

    def __init__(self, workspace_id: str, industry: str, branch: str):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch

    def _event(
        self,
        type: EventType,
        label: str,
        steps: list[dict],
        *,
        stage: WorkflowState = WorkflowState.APPROVED_FYP,
        status: EventStatus = EventStatus.RUNNING,
        allowed_actions: list[AllowedAction] | None = None,
        brain_patch: dict | None = None,
        **extra,
    ) -> GreyEvent:
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
        return self._event(
            EventType.PROJECT_DEFINITION_STARTED, "Defining your project", _steps(None, False),
            brain_patch={"project_definition_status": "running"},
        )

    def progress(self, progress: DefinitionProgress) -> GreyEvent:
        steps = _steps(progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.PROJECT_DEFINITION_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.PROJECT_DEFINITION_PROGRESS, SAVING_LABEL, _steps(SAVING_STEP, False))

    def ready(self, view: ProjectDefinitionView) -> GreyEvent:
        """The definition to review. The student may move features, then must approve the scope."""
        return self._event(
            EventType.PROJECT_DEFINITION_READY,
            "Your project definition is ready",
            _steps(SAVING_STEP, current_done=True),
            stage=WorkflowState.SCOPE,
            status=EventStatus.AWAITING_USER,
            allowed_actions=REVIEW_ACTIONS,
            brain_patch={"workflow_state": WorkflowState.SCOPE.value, **_view_patch(view)},
            definition=view.model_dump(mode="json"),
        )

    def failed(self) -> GreyEvent:
        """A safe failure event; the real error is stored on the run, not sent."""
        return self._event(
            EventType.PROJECT_DEFINITION_FAILED,
            "Your project could not be defined",
            _steps(None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.DEFINE_PROJECT],
            brain_patch={"project_definition_status": "failed"},
            message=FAILED_MESSAGE,
        )


def scope_updated_event(workspace_id: str, view: ProjectDefinitionView, moved_title: str) -> GreyEvent:
    """The student moved a feature. Still reviewing: move more, or approve."""
    return build_event(
        type=EventType.SCOPE_UPDATED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.SCOPE.value,
        status=EventStatus.AWAITING_USER,
        data={"definition": view.model_dump(mode="json"), "moved": moved_title},
        brain_patch=_view_patch(view),
        allowed_actions=REVIEW_ACTIONS,
    )


def scope_approved_event(workspace_id: str, view: ProjectDefinitionView) -> GreyEvent:
    """The student approved the scope. Release 0.6 ends here."""
    return build_event(
        type=EventType.SCOPE_APPROVED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.SCOPE_APPROVED.value,
        status=EventStatus.COMPLETE,
        data={"definition": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.SCOPE_APPROVED.value, **_view_patch(view)},
        allowed_actions=[],
    )
