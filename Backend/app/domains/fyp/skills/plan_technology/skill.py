"""
PlanTechnologySkill — recommends a focused technology stack and the hardware
the student's approved project needs (product blueprint §27–29, Release 0.10).

  LLMGateway (profile "structured_reasoning") — the ONE place the model is called
  check_plan_draft (code)                     — rejects replies that break the rules

Grey makes decisions, not option lists (§28): one choice per needed area,
each with a reason that fits THIS project. One retry, then
TechnologyPlanRejectedError. The skill never reads or writes the database.
"""
from collections import Counter

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import ProjectDefinition, ScopeKind
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.plan_technology import INSTRUCTIONS, PROMPT_VERSION, REPLAN_REQUEST
from app.domains.fyp.skills.fyp_design_shared import brief_for_model
from app.domains.fyp.skills.plan_technology.schemas import (
    LLMTechnologyPlanDraft,
    PlanTechnologyInput,
    PlanTechnologyOutput,
    TechnologyPhase,
    TechnologyProgress,
    TechnologyProgressCallback,
)
from app.domains.fyp.skills.plan_technology.validation import check_plan_draft

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 3_500

PLANNING_LABEL = "Choosing a focused technology stack"
REPLANNING_LABEL = "Making the plan simpler and cheaper"
CHECKING_LABEL = "Checking hardware, costs and the rules"


class TechnologyPlanRejectedError(Exception):
    """The model's technology plan failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def _items(definition: ProjectDefinition, kind: ScopeKind) -> list[str]:
    return [item.title for item in definition.scope if item.kind == kind]


def build_llm_input(input: PlanTechnologyInput) -> dict:
    """What the model sees: the approved decisions (no ids, links or organizations)."""
    strategy, design = input.strategy, input.design
    llm_input: dict = {
        "industry": input.industry,
        "branch": input.branch,
        "functional_area": input.area.functional_area,
        "problem": brief_for_model(input.problem),
        "approved_design": {
            "title": design.title, "target_user": design.target_user,
            "system_input": design.system_input, "system_output": design.system_output,
        },
        "core_features": _items(input.definition, ScopeKind.CORE),
        "modules": [module.name for module in input.definition.proposed_solution.modules],
        "ai_strategy": {
            "uses_ai": uses_ai(strategy.necessity),
            "task_type": strategy.task_type.value if strategy.task_type else "none",
            "primary_approach": strategy.primary_strategy.approach.value if strategy.primary_strategy else "none",
        },
        "selected_dataset": {"name": input.dataset.name, "kind": input.dataset.kind.value, "size": input.dataset.size},
        "model_plan": {
            "summary": input.models.summary,
            "options": [{"name": o.name, "kind": o.kind.value, "use": o.use.value} for o in input.models.options],
        },
    }
    if input.preference is not None and input.previous_plan is not None:
        llm_input["replan"] = {
            "student_request": REPLAN_REQUEST,
            "previous_answer": input.previous_plan.model_dump(mode="json"),
        }
    return llm_input


class PlanTechnologySkill(Skill):
    metadata = SkillMetadata(
        name="plan_technology",
        description=(
            "Recommend one technology per needed stack area, with a project-specific reason, "
            "and the hardware the project needs, with cost and alternatives."
        ),
        version="0.10.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: PlanTechnologyInput,
        on_progress: TechnologyProgressCallback | None = None,
    ) -> PlanTechnologyOutput:
        """
        Plan the technology.

        Raises:
            TechnologyPlanRejectedError: the reply failed the checks twice.
            LLMError subclasses:         the gateway could not get an answer.
        """
        async def report(phase: TechnologyPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(TechnologyProgress(phase=phase, label=label))

        llm_input = build_llm_input(input)
        rejections: Counter = Counter()
        first_label = REPLANNING_LABEL if input.preference is not None else PLANNING_LABEL
        for _ in range(MAX_ATTEMPTS):
            await report(TechnologyPhase.PLANNING, first_label)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMTechnologyPlanDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            await report(TechnologyPhase.CHECKING, CHECKING_LABEL)
            plan, reason = check_plan_draft(result.output, input)
            if plan is not None:
                return PlanTechnologyOutput(
                    plan=plan, provider=result.provider, model=result.model,
                    prompt_version=PROMPT_VERSION, rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Give exactly one technology per area (no 'A or B'), 2-6 "
                "areas, each area once; include ai_ml only (and always) when the project uses AI, training only "
                "when it uses AI; include a frontend or a backend; 1-5 hardware items with listed kinds and costs; "
                "a high-cost item needs an alternative; no links; keep every text short."
            )}
        raise TechnologyPlanRejectedError("The technology plan failed Grey's checks twice.", dict(rejections))
