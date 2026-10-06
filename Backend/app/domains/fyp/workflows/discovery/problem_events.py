"""
Problem events — turns problem-extraction progress and results into GreyEvents.

While Grey works, the student sees a short checklist:

    ✓ Reviewing your evidence
    ● Identifying real problems organizations face
    ○ Checking each problem against its sources
    ○ Saving problem options to your Project Brain

Then the options themselves (problem_options_ready), or a calm failure
message (problem_extraction_failed), and later the student's choice
(problem_selected).

Only safe content is sent: step labels, the validated options and their
cited sources. Never prompts, model reasoning or raw error messages.
"""
from app.core.brain.schemas import ProblemRun, StoredProblemCandidate, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.problem_extraction.schemas import ProblemPhase, ProblemProgress
from app.domains.fyp.skills.problem_extraction.skill import LABELS

SAVING_STEP = "saving_problems"
SAVING_LABEL = "Saving problem options to your Project Brain"
STARTING_LABEL = "Looking for real problems in your evidence"

# (step id, label) in the order the student sees them.
PROBLEM_STEPS: list[tuple[str, str]] = [
    *((phase.value, LABELS[phase]) for phase in ProblemPhase),
    (SAVING_STEP, SAVING_LABEL),
]

FAILED_MESSAGE = (
    "Grey couldn't finish finding problems right now. Your evidence is safe — please try again."
)
NOT_ENOUGH_EVIDENCE_MESSAGE = (
    "Grey couldn't find enough strong evidence to suggest problems. Try running the research again."
)


def _steps(current: str | None, current_done: bool) -> list[dict]:
    """Steps before `current` are done, `current` is active (or done), the rest are pending."""
    ids = [step_id for step_id, _ in PROBLEM_STEPS]
    position = ids.index(current) if current is not None else -1
    steps = []
    for index, (step_id, label) in enumerate(PROBLEM_STEPS):
        if index < position or (index == position and current_done):
            state = "done"
        elif index == position:
            state = "active"
        else:
            state = "pending"
        steps.append({"id": step_id, "label": label, "state": state})
    return steps


class ProblemEventBuilder:
    """Builds the problem events for one project."""

    def __init__(self, workspace_id: str, industry: str, branch: str) -> None:
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch

    def _event(
        self,
        type: EventType,
        label: str,
        steps: list[dict],
        *,
        stage: WorkflowState = WorkflowState.EVIDENCE_RESEARCH,
        status: EventStatus = EventStatus.RUNNING,
        allowed_actions: list[AllowedAction] | None = None,
        brain_patch: dict | None = None,
        **extra,
    ) -> GreyEvent:
        return build_event(
            type=type,
            workspace_id=self.workspace_id,
            workflow="discovery",
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
            EventType.PROBLEM_EXTRACTION_STARTED, STARTING_LABEL, _steps(None, False),
            brain_patch={"problem_status": "running"},
        )

    def progress(self, progress: ProblemProgress) -> GreyEvent:
        return self._event(
            EventType.PROBLEM_EXTRACTION_PROGRESS, progress.label, _steps(progress.phase.value, False),
        )

    def saving(self) -> GreyEvent:
        return self._event(EventType.PROBLEM_EXTRACTION_PROGRESS, SAVING_LABEL, _steps(SAVING_STEP, False))

    def options_ready(self, run: ProblemRun, options: list[StoredProblemCandidate]) -> GreyEvent:
        """The problem cards, with their sources. The student must now choose one."""
        return self._event(
            EventType.PROBLEM_OPTIONS_READY,
            "Problem options ready",
            _steps(SAVING_STEP, current_done=True),
            stage=WorkflowState.PROBLEM_OPTIONS,
            status=EventStatus.AWAITING_USER,
            allowed_actions=[AllowedAction.SELECT_PROBLEM],
            brain_patch={
                "workflow_state": WorkflowState.PROBLEM_OPTIONS.value,
                "problem_status": "options_ready",
                "problem_option_count": len(options),
            },
            problems=[option.model_dump(mode="json") for option in options],
            summary={
                "options": len(options),
                "drafts_checked": run.candidates_generated,
                "provider": run.provider,
            },
        )

    def failed(self, not_enough_evidence: bool = False) -> GreyEvent:
        """A safe failure event. The real error is stored on the problem run, not sent."""
        return self._event(
            EventType.PROBLEM_EXTRACTION_FAILED,
            "Problems could not be found",
            _steps(None, False),
            status=EventStatus.BLOCKED,
            # Too little evidence → research again; anything else → simply try again.
            allowed_actions=[AllowedAction.START_RESEARCH if not_enough_evidence else AllowedAction.EXTRACT_PROBLEMS],
            brain_patch={"problem_status": "failed"},
            message=NOT_ENOUGH_EVIDENCE_MESSAGE if not_enough_evidence else FAILED_MESSAGE,
        )


def problem_selected_event(workspace_id: str, problem: StoredProblemCandidate) -> GreyEvent:
    """
    The student's choice is saved and the discovery stage ends. Next, Grey turns
    the problem into an FYP (the FYP Design workflow, Release 0.5).
    """
    return build_event(
        type=EventType.PROBLEM_SELECTED,
        workspace_id=workspace_id,
        workflow="discovery",
        stage=WorkflowState.PROBLEM_SELECTED.value,
        status=EventStatus.COMPLETE,
        data={"problem": problem.model_dump(mode="json")},
        brain_patch={
            "workflow_state": WorkflowState.PROBLEM_SELECTED.value,
            "selected_problem_id": problem.id,
            "selected_problem_title": problem.title,
        },
        allowed_actions=[AllowedAction.DESIGN_FYP],
    )
