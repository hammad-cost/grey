"""
PlanAIStrategySkill — checks whether the student's approved project really
needs AI and, if it does, which AI task and implementation approach fit
(product blueprint §22–23, Release 0.7).

  LLMGateway (profile "structured_reasoning") — the ONE place the model is called
  check_strategy_draft (code)                 — rejects replies that break the rules

If a reply fails the checks, the skill asks once more (naming the rule that
failed), then gives up with AIStrategyRejectedError.

Grey never forces AI into a project: "rule-based", "optimization" and "AI is
not required" are as valid as any AI verdict. The strategy is described in
general terms; specific datasets, models and APIs are chosen in later stages.

What the skill does NOT do (by design): read or write the database (the
runner passes everything in), count re-checks, or decide the next stage.
"""
from collections import Counter

from app.core.brain.schemas import ProjectDefinition, ScopeKind
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.plan_ai_strategy import INSTRUCTIONS, PREFERENCE_REQUESTS, PROMPT_VERSION
from app.domains.fyp.skills.fyp_design_shared import brief_for_model
from app.domains.fyp.skills.plan_ai_strategy.schemas import (
    AIStrategyPhase,
    AIStrategyProgress,
    AIStrategyProgressCallback,
    LLMAIStrategyDraft,
    PlanAIStrategyInput,
    PlanAIStrategyOutput,
)
from app.domains.fyp.skills.plan_ai_strategy.validation import check_strategy_draft

MAX_ATTEMPTS = 2
# A short JSON reply plus the model's hidden reasoning; kept modest for Groq's
# free tier (about 8,000 tokens per minute).
MAX_OUTPUT_TOKENS = 3_000

CHECKING_NEED_LABEL = "Checking whether your project really needs AI"
RECHECKING_LABEL = "Checking again with your preference"
CHECKING_ANSWER_LABEL = "Checking the answer against your approved scope"


class AIStrategyRejectedError(Exception):
    """The model's AI strategy failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def _features(definition: ProjectDefinition, kind: ScopeKind) -> list[dict]:
    return [{"title": i.title, "description": i.description} for i in definition.scope if i.kind == kind]


def build_llm_input(input: PlanAIStrategyInput) -> dict:
    """What the model sees: the problem, the approved design and definition (no ids, links or organizations)."""
    definition = input.definition
    llm_input: dict = {
        "industry": input.industry,
        "branch": input.branch,
        "functional_area": input.area.functional_area,
        "specific_area": input.area.specific_area,
        "problem": brief_for_model(input.problem),
        "approved_design": input.design.model_dump(mode="json"),
        "project_definition": {
            "problem_definition": definition.problem_definition.model_dump(mode="json"),
            "proposed_solution": definition.proposed_solution.model_dump(mode="json"),
            "core_features": _features(definition, ScopeKind.CORE),
            "optional_features": _features(definition, ScopeKind.OPTIONAL),
            "out_of_scope": [item["title"] for item in _features(definition, ScopeKind.OUT_OF_SCOPE)],
        },
    }
    if input.preference is not None and input.previous_strategy is not None:
        llm_input["recheck"] = {
            "student_request": PREFERENCE_REQUESTS[input.preference.value],
            "previous_answer": input.previous_strategy.model_dump(mode="json"),
        }
    return llm_input


class PlanAIStrategySkill(Skill):
    metadata = SkillMetadata(
        name="plan_ai_strategy",
        description=(
            "Check whether the student's approved project really needs AI and, if it does, "
            "choose the AI task and one primary (plus an optional fallback) implementation approach."
        ),
        version="0.7.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: PlanAIStrategyInput,
        on_progress: AIStrategyProgressCallback | None = None,
    ) -> PlanAIStrategyOutput:
        """
        Check the AI need and plan the strategy.

        Raises:
            AIStrategyRejectedError: the reply failed the checks twice.
            LLMError subclasses:      the gateway could not get an answer.
        """
        async def report(phase: AIStrategyPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(AIStrategyProgress(phase=phase, label=label))

        llm_input = build_llm_input(input)
        rejections: Counter = Counter()
        thinking_label = RECHECKING_LABEL if input.preference is not None else CHECKING_NEED_LABEL

        for _ in range(MAX_ATTEMPTS):
            await report(AIStrategyPhase.CHECKING_AI_NEED, thinking_label)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMAIStrategyDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))

            await report(AIStrategyPhase.CHECKING_ANSWER, CHECKING_ANSWER_LABEL)
            strategy, reason = check_strategy_draft(result.output, input)
            if strategy is not None:
                return PlanAIStrategyOutput(
                    strategy=strategy,
                    provider=result.provider,
                    model=result.model,
                    prompt_version=PROMPT_VERSION,
                    rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            # Ask once more, naming the rule that failed (no reply text is echoed back).
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Use only the listed values for necessity, task_type and "
                "approach; give AI details only when the verdict uses AI; traditional_ml uses train_model or "
                "hybrid; existing_model uses pretrained_model or use_api; the fallback must differ from the "
                "primary approach; never name organizations, datasets, models, libraries, APIs or technologies; "
                "never include links; keep every text short."
            )}

        raise AIStrategyRejectedError("The AI strategy failed Grey's checks twice.", dict(rejections))
