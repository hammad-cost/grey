"""
AssessFeasibilitySkill — judges whether the student's approved FYP is realistic
(product blueprint §32, Release 0.12).

  facts.py (code)                             — six dimensions decided from Project Brain facts
  LLMGateway (profile "structured_reasoning") — the ONE model call: seven judgement
                                                dimensions, main risks, a summary
  check_feasibility_draft (code)              — checks the judgement and builds the report;
                                                the overall High / Medium / Low is computed in code

One retry, then FeasibilityRejectedError. The skill never reads or writes the database.
"""
from collections import Counter

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import ScopeKind
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.assess_feasibility import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.assess_feasibility.facts import fact_dimensions
from app.domains.fyp.skills.assess_feasibility.schemas import (
    AssessFeasibilityInput,
    AssessFeasibilityOutput,
    FeasibilityPhase,
    FeasibilityProgress,
    FeasibilityProgressCallback,
    LLMFeasibilityDraft,
)
from app.domains.fyp.skills.assess_feasibility.validation import check_feasibility_draft
from app.domains.fyp.skills.fyp_design_shared import brief_for_model

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 3_500

FACTS_LABEL = "Checking the facts in your Project Brain"
JUDGING_LABEL = "Judging time, complexity, risks and ethics"
CHECKING_LABEL = "Computing the overall feasibility"


class FeasibilityRejectedError(Exception):
    """The model's judgement failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def build_llm_input(input: AssessFeasibilityInput) -> dict:
    """What the model sees: the approved decisions and the fact dimensions (no ids, links or organizations)."""
    strategy, technical = input.strategy, input.technical
    return {
        "industry": input.industry,
        "branch": input.branch,
        "problem": brief_for_model(input.problem),
        "approved_design": {"title": input.design.title, "summary": input.design.summary,
                            "main_contribution": input.design.main_contribution},
        "core_features": [i.title for i in input.definition.scope if i.kind == ScopeKind.CORE],
        "ai_strategy": {"uses_ai": uses_ai(strategy.necessity), "necessity": strategy.necessity.value,
                        "task_type": strategy.task_type.value if strategy.task_type else "none"},
        "dataset": {"name": input.dataset.name, "kind": input.dataset.kind.value,
                    "limitations": input.dataset.limitations},
        "model_plan": [{"name": o.name, "kind": o.kind.value, "use": o.use.value} for o in input.models.options],
        "technology_stack": [{"area": c.area.value, "choice": c.choice} for c in input.technology.stack],
        "architecture": [c.name for c in technical.architecture.components],
        "facts": [{"dimension": d.dimension.value, "level": d.level.value, "finding": d.finding}
                  for d in fact_dimensions(input)],
    }


class AssessFeasibilitySkill(Skill):
    metadata = SkillMetadata(
        name="assess_feasibility",
        description=(
            "Judge whether the approved FYP is realistic: six dimensions from facts, seven judged by "
            "the model, the main risks with mitigations, and an overall High / Medium / Low computed in code."
        ),
        version="0.12.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: AssessFeasibilityInput,
        on_progress: FeasibilityProgressCallback | None = None,
    ) -> AssessFeasibilityOutput:
        """
        Assess the feasibility.

        Raises:
            FeasibilityRejectedError: the judgement failed the checks twice.
            LLMError subclasses:      the gateway could not get an answer.
        """
        async def report(phase: FeasibilityPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(FeasibilityProgress(phase=phase, label=label))

        await report(FeasibilityPhase.FACTS, FACTS_LABEL)
        llm_input = build_llm_input(input)
        rejections: Counter = Counter()
        for _ in range(MAX_ATTEMPTS):
            await report(FeasibilityPhase.JUDGING, JUDGING_LABEL)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMFeasibilityDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            await report(FeasibilityPhase.CHECKING, CHECKING_LABEL)
            feasibility, reason = check_feasibility_draft(result.output, input)
            if feasibility is not None:
                return AssessFeasibilityOutput(
                    report=feasibility, provider=result.provider, model=result.model,
                    prompt_version=PROMPT_VERSION, rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Judge exactly the seven listed dimensions once each with "
                "level favourable, moderate or concern; 1-5 main risks with mitigations; do not state an overall "
                "rating; no links; keep every text short."
            )}
        raise FeasibilityRejectedError("The feasibility judgement failed Grey's checks twice.", dict(rejections))
