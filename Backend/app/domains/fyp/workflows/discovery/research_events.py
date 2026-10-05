"""
Research events — turns research progress into typed GreyEvents for the frontend.

The student sees a short checklist while Grey researches:

    ✓ Identifying relevant organizations
    ✓ Reviewing authoritative sources
    ● Checking research
    ○ Checking datasets
    ○ Evaluating evidence quality
    ○ Saving evidence to your Project Brain

    11 sources found • 7 high-quality sources

Every event carries the whole checklist (data.steps), so the frontend just
renders what it receives — it never needs to know the research plan.

Only safe activity is sent: step labels and source counts. Never reasoning,
prompts, queries, or raw error messages.
"""
from app.core.brain.schemas import ResearchCategory, ResearchRun, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType, GreyEvent, build_event
from app.domains.fyp.skills.research_evidence.queries import CATEGORY_LABELS, EVALUATING_LABEL
from app.domains.fyp.skills.research_evidence.schemas import (
    ResearchPhase,
    ResearchProgress,
    ResearchSummary,
)

EVALUATING_STEP = "evaluating"
STORING_STEP = "storing"
STORING_LABEL = "Saving evidence to your Project Brain"
STARTING_LABEL = "Starting research"

# (step id, label) in the order the student sees them.
RESEARCH_STEPS: list[tuple[str, str]] = [
    *((category.value, label) for category, label in CATEGORY_LABELS.items()),
    (EVALUATING_STEP, EVALUATING_LABEL),
    (STORING_STEP, STORING_LABEL),
]

FAILED_MESSAGE = "Grey couldn't finish researching right now. Your earlier evidence is safe — please try again."

# Skill phase → event type
_PHASE_EVENT = {
    ResearchPhase.SEARCHING_SOURCES: EventType.SEARCHING_SOURCES,
    ResearchPhase.SOURCES_FOUND: EventType.SOURCES_FOUND,
    ResearchPhase.EVALUATING_EVIDENCE: EventType.EVALUATING_EVIDENCE,
}


def _steps(current: str | None, current_done: bool) -> list[dict]:
    """
    The checklist: steps before `current` are done, `current` is active (or done),
    steps after it are pending. current=None means nothing has started yet.
    """
    ids = [step_id for step_id, _ in RESEARCH_STEPS]
    position = ids.index(current) if current is not None else -1
    steps = []
    for index, (step_id, label) in enumerate(RESEARCH_STEPS):
        if index < position or (index == position and current_done):
            state = "done"
        elif index == position:
            state = "active"
        else:
            state = "pending"
        steps.append({"id": step_id, "label": label, "state": state})
    return steps


class ResearchEventBuilder:
    """Builds the research events for one project, keeping the latest source counts."""

    def __init__(self, workspace_id: str, industry: str, branch: str) -> None:
        self.workspace_id = workspace_id
        self.industry = industry
        self.branch = branch
        self.sources_found = 0
        self.high_quality_sources = 0

    def _event(
        self,
        type: EventType,
        label: str,
        steps: list[dict],
        status: EventStatus = EventStatus.RUNNING,
        allowed_actions: list[AllowedAction] | None = None,
        brain_patch: dict | None = None,
        **extra,
    ) -> GreyEvent:
        return build_event(
            type=type,
            workspace_id=self.workspace_id,
            workflow="discovery",
            stage=WorkflowState.EVIDENCE_RESEARCH.value,
            status=status,
            data={
                "industry": self.industry,
                "branch": self.branch,
                "label": label,
                "steps": steps,
                "completed_steps": sum(1 for s in steps if s["state"] == "done"),
                "total_steps": len(steps),
                "sources_found": self.sources_found,
                "high_quality_sources": self.high_quality_sources,
                **extra,
            },
            brain_patch=brain_patch or {},
            allowed_actions=allowed_actions or [],
        )

    def started(self) -> GreyEvent:
        return self._event(
            EventType.RESEARCH_STARTED, STARTING_LABEL, _steps(None, False),
            brain_patch={"research_status": "running"},
        )

    def progress(self, progress: ResearchProgress) -> GreyEvent:
        """searching_sources / sources_found / evaluating_evidence, from the skill's progress."""
        self.sources_found = progress.sources_found
        self.high_quality_sources = progress.high_quality_sources

        if progress.phase == ResearchPhase.EVALUATING_EVIDENCE:
            steps = _steps(EVALUATING_STEP, current_done=False)
        else:
            category = progress.category or ResearchCategory.ORGANIZATIONS
            steps = _steps(category.value, current_done=progress.phase == ResearchPhase.SOURCES_FOUND)

        return self._event(_PHASE_EVENT[progress.phase], progress.label, steps)

    def storing(self) -> GreyEvent:
        return self._event(EventType.STORING_EVIDENCE, STORING_LABEL, _steps(STORING_STEP, False))

    def completed(self, run: ResearchRun, summary: ResearchSummary) -> GreyEvent:
        self.sources_found = run.sources_found
        self.high_quality_sources = run.high_quality_count
        return self._event(
            EventType.RESEARCH_COMPLETED,
            "Research complete",
            _steps(STORING_STEP, current_done=True),
            status=EventStatus.COMPLETE,
            brain_patch={
                "research_status": "complete",
                "evidence_count": run.sources_found,
                "high_quality_evidence_count": run.high_quality_count,
            },
            summary={
                "total_sources": summary.total_sources,
                "high_quality_count": summary.high_quality_count,
                "by_tier": {tier.value: count for tier, count in summary.by_tier.items()},
                "by_category": {cat.value: count for cat, count in summary.by_category.items()},
                "provider": summary.provider,
            },
        )

    def failed(self) -> GreyEvent:
        """A safe failure event. The real error is stored on the research run, not sent."""
        return self._event(
            EventType.RESEARCH_FAILED,
            "Research could not be completed",
            _steps(None, False),
            status=EventStatus.BLOCKED,
            allowed_actions=[AllowedAction.START_RESEARCH],
            brain_patch={"research_status": "failed"},
            message=FAILED_MESSAGE,
        )
