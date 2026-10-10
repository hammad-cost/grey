"""
PrepareSupervisorBriefSkill — gets the student ready for the supervisor
(product blueprint §33–35, Release 0.13).

  readiness.py (code)   — the nine readiness checks and the 14-line summary,
                          built only from approved decisions (no AI, nothing can drift)
  LLMGateway            — the ONE model call ("structured_reasoning"): talking
                          points for the ten likely supervisor questions
  check_talking_points  — checks the reply and builds the full brief

One retry, then SupervisorBriefRejectedError. The skill never reads or writes the database.
"""
from collections import Counter

from app.core.brain.schemas import ReadinessStatus
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.prepare_supervisor_brief import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.fyp_design_shared import brief_for_model
from app.domains.fyp.skills.prepare_supervisor_brief.readiness import readiness_checks, supervisor_summary
from app.domains.fyp.skills.prepare_supervisor_brief.schemas import (
    QUESTIONS,
    BriefPhase,
    BriefProgress,
    BriefProgressCallback,
    LLMTalkingPointsDraft,
    SupervisorBriefInput,
    SupervisorBriefOutput,
)
from app.domains.fyp.skills.prepare_supervisor_brief.validation import check_talking_points

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 4_000

CHECKING_LABEL = "Running the supervisor readiness checks"
WRITING_LABEL = "Preparing talking points for likely questions"
REVIEWING_LABEL = "Checking every question is answered"


class SupervisorBriefRejectedError(Exception):
    """The model's talking points failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def build_llm_input(input: SupervisorBriefInput) -> dict:
    """What the model sees: the summary, checks needing attention, evidence points, risks, the questions."""
    return {
        "summary": [{"label": i.label, "value": i.value} for i in supervisor_summary(input)],
        "checks_needing_attention": [
            {"question": c.question, "detail": c.detail}
            for c in readiness_checks(input) if c.status == ReadinessStatus.ATTENTION
        ],
        "problem": brief_for_model(input.problem),
        "target_user": input.design.target_user,
        "out_of_scope": [i.title for i in input.definition.scope if i.kind.value == "out_of_scope"],
        "dataset_limitations": input.dataset.limitations,
        "main_risks": [{"risk": r.risk, "mitigation": r.mitigation} for r in input.feasibility.main_risks],
        "evaluation_goals": [{"metric": m.metric.value, "goal": m.goal} for m in input.technical.evaluation.metrics],
        "baseline": input.technical.evaluation.baseline or "",
        "questions": [{"id": qid.value, "question": text} for qid, text in QUESTIONS.items()],
    }


class PrepareSupervisorBriefSkill(Skill):
    metadata = SkillMetadata(
        name="prepare_supervisor_brief",
        description=(
            "Run the supervisor readiness checks, assemble the supervisor-ready summary from approved "
            "decisions, and write talking points for the ten likely supervisor questions."
        ),
        version="0.13.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: SupervisorBriefInput,
        on_progress: BriefProgressCallback | None = None,
    ) -> SupervisorBriefOutput:
        """
        Prepare the brief.

        Raises:
            SupervisorBriefRejectedError: the talking points failed the checks twice.
            LLMError subclasses:          the gateway could not get an answer.
        """
        async def report(phase: BriefPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(BriefProgress(phase=phase, label=label))

        await report(BriefPhase.CHECKING, CHECKING_LABEL)
        llm_input = build_llm_input(input)
        rejections: Counter = Counter()
        for _ in range(MAX_ATTEMPTS):
            await report(BriefPhase.WRITING, WRITING_LABEL)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMTalkingPointsDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            await report(BriefPhase.REVIEWING, REVIEWING_LABEL)
            brief, reason = check_talking_points(result.output, input)
            if brief is not None:
                return SupervisorBriefOutput(
                    brief=brief, provider=result.provider, model=result.model,
                    prompt_version=PROMPT_VERSION, rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Answer every one of the ten question ids exactly once, "
                "with 2-4 short talking points each; no links."
            )}
        raise SupervisorBriefRejectedError("The talking points failed Grey's checks twice.", dict(rejections))
