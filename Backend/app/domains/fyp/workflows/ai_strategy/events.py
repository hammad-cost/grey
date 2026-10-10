"""
AI strategy events — turns the AI necessity check's progress and results into GreyEvents.

While Grey works, the student sees a short checklist:

    ✓ Checking whether your project really needs AI
    ● Checking the answer against your approved scope
    ○ Saving it to your Project Brain

then the result to review (ai_strategy_ready) or a calm failure message
(ai_strategy_failed); later the approval (ai_strategy_approved).

Only safe content is sent: step labels and the checked, saved results.
Never prompts, model reasoning or raw error messages.
"""
from app.core.brain.schemas import AIStrategyStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.plan_ai_strategy import AIStrategyPhase, AIStrategyProgress
from app.domains.fyp.skills.plan_ai_strategy.skill import (
    CHECKING_ANSWER_LABEL,
    CHECKING_NEED_LABEL,
    RECHECKING_LABEL,
)
from app.domains.fyp.workflows.ai_strategy.view import AIStrategyView

WORKFLOW = "ai_strategy"
SAVING_STEP = "saving_ai_strategy"
SAVING_LABEL = "Saving it to your Project Brain"

FAILED_MESSAGE = (
    "Grey couldn't finish checking whether your project needs AI right now. "
    "Your approved scope is safe — please try again."
)
RECHECK_FAILED_MESSAGE = (
    "Grey couldn't check again right now. Your current AI strategy is kept, and the re-check wasn't used up."
)


def _steps(first_label: str, current: str | None, current_done: bool) -> list[dict]:
    """Steps before `current` are done, `current` is active (or done), the rest are pending."""
    steps_list = [
        (AIStrategyPhase.CHECKING_AI_NEED.value, first_label),
        (AIStrategyPhase.CHECKING_ANSWER.value, CHECKING_ANSWER_LABEL),
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


def review_actions(view: AIStrategyView) -> list[AllowedAction]:
    """While reviewing: approve, and check again only when a re-check is still possible."""
    actions = [AllowedAction.APPROVE_AI_STRATEGY]
    if view.available_rechecks:
        actions.append(AllowedAction.RECHECK_AI_STRATEGY)
    return actions


def _view_patch(view: AIStrategyView) -> dict:
    strategy = view.strategy
    if strategy is None:
        return {}
    return {
        "ai_strategy_id": strategy.id,
        "ai_strategy_status": strategy.status.value,
        "ai_necessity": strategy.strategy.necessity.value,
        "ai_rechecks_left": view.rechecks_left,
    }


class AIStrategyEventBuilder:
    """Builds the events for one AI necessity check (the first one or a re-check)."""

    def __init__(self, workspace_id: str, industry: str, branch: str, *, recheck: bool):
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.recheck = recheck
        self.first_label = RECHECKING_LABEL if recheck else CHECKING_NEED_LABEL
        # Where the project is while Grey works: a re-check happens during the review.
        self.working_stage = WorkflowState.AI_STRATEGY if recheck else WorkflowState.SCOPE_APPROVED

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
                "recheck": self.recheck,
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        label = "Checking again with your preference" if self.recheck else "Checking whether your project needs AI"
        return self._event(
            EventType.AI_STRATEGY_STARTED, label, _steps(self.first_label, None, False),
            brain_patch={"ai_strategy_status": "running"},
        )

    def progress(self, progress: AIStrategyProgress) -> GreyEvent:
        steps = _steps(self.first_label, progress.phase.value, False)
        label = next((s["label"] for s in steps if s["id"] == progress.phase.value), progress.label)
        return self._event(EventType.AI_STRATEGY_PROGRESS, label, steps)

    def saving(self) -> GreyEvent:
        return self._event(EventType.AI_STRATEGY_PROGRESS, SAVING_LABEL, _steps(self.first_label, SAVING_STEP, False))

    def ready(self, view: AIStrategyView) -> GreyEvent:
        """The result to review. The student may check again, then must approve."""
        return self._event(
            EventType.AI_STRATEGY_READY,
            "Your AI check is ready",
            _steps(self.first_label, SAVING_STEP, current_done=True),
            stage=WorkflowState.AI_STRATEGY,
            status=EventStatus.AWAITING_USER,
            allowed_actions=review_actions(view),
            brain_patch={"workflow_state": WorkflowState.AI_STRATEGY.value, **_view_patch(view)},
            ai_strategy=view.model_dump(mode="json"),
        )

    def failed(self, view: AIStrategyView | None) -> GreyEvent:
        """
        A safe failure event; the real error is stored on the run, not sent.
        A failed re-check keeps the current strategy, so the review goes on.
        """
        draft = view is not None and view.strategy is not None and view.strategy.status == AIStrategyStatus.DRAFT
        if draft:
            return self._event(
                EventType.AI_STRATEGY_FAILED,
                "Grey couldn't check again",
                _steps(self.first_label, None, False),
                stage=WorkflowState.AI_STRATEGY,
                status=EventStatus.AWAITING_USER,
                allowed_actions=review_actions(view),
                brain_patch={"ai_strategy_status": "draft", **_view_patch(view)},
                ai_strategy=view.model_dump(mode="json"),
                message=RECHECK_FAILED_MESSAGE,
            )
        return self._event(
            EventType.AI_STRATEGY_FAILED,
            "Grey couldn't check whether your project needs AI",
            _steps(self.first_label, None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.CHECK_AI_NEED],
            brain_patch={"ai_strategy_status": "failed"},
            message=FAILED_MESSAGE,
        )


def ai_strategy_approved_event(workspace_id: str, view: AIStrategyView) -> GreyEvent:
    """The student approved the AI strategy. Release 0.7 ends here."""
    return build_event(
        type=EventType.AI_STRATEGY_APPROVED,
        workspace_id=workspace_id,
        workflow=WORKFLOW,
        stage=WorkflowState.AI_STRATEGY_APPROVED.value,
        status=EventStatus.COMPLETE,
        data={"ai_strategy": view.model_dump(mode="json")},
        brain_patch={"workflow_state": WorkflowState.AI_STRATEGY_APPROVED.value, **_view_patch(view)},
        allowed_actions=[],
    )
