"""
DesignArchitectureSkill — designs the system architecture and the evaluation
plan from the student's approved decisions (product blueprint §30–31, Release 0.11).

  LLMGateway (profile "structured_reasoning") — the ONE place the model is called
  check_plan_draft (code)                     — rejects replies that break the rules

The architecture is derived from the approved design, scope, dataset, models and
stack; components may only name technologies that were approved. One retry, then
ArchitecturePlanRejectedError. The skill never reads or writes the database.
"""
from collections import Counter

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.architecture_rules import allowed_metrics
from app.core.brain.schemas import ScopeKind
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.design_architecture import INSTRUCTIONS, PROMPT_VERSION, REDESIGN_REQUEST
from app.domains.fyp.skills.design_architecture.schemas import (
    ArchitecturePhase,
    ArchitectureProgress,
    ArchitectureProgressCallback,
    DesignArchitectureInput,
    DesignArchitectureOutput,
    LLMTechnicalPlanDraft,
)
from app.domains.fyp.skills.design_architecture.validation import check_plan_draft
from app.domains.fyp.skills.fyp_design_shared import brief_for_model

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 4_000

DESIGNING_LABEL = "Designing your system architecture and evaluation plan"
REDESIGNING_LABEL = "Making the architecture simpler"
CHECKING_LABEL = "Checking every part is connected and measurable"


class ArchitecturePlanRejectedError(Exception):
    """The model's technical plan failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def build_llm_input(input: DesignArchitectureInput) -> dict:
    """What the model sees: the approved decisions (no ids, links or organizations)."""
    strategy, design, definition = input.strategy, input.design, input.definition
    llm_input: dict = {
        "industry": input.industry,
        "branch": input.branch,
        "problem": brief_for_model(input.problem),
        "approved_design": {
            "title": design.title, "summary": design.summary, "target_user": design.target_user,
            "system_input": design.system_input, "system_output": design.system_output,
        },
        "core_features": [item.title for item in definition.scope if item.kind == ScopeKind.CORE],
        "modules": [{"name": m.name, "purpose": m.purpose} for m in definition.proposed_solution.modules],
        "workflow_steps": definition.proposed_solution.workflow_steps,
        "ai_strategy": {
            "uses_ai": uses_ai(strategy.necessity),
            "ai_component": strategy.ai_component or "",
            "task_type": strategy.task_type.value if strategy.task_type else "none",
            "allowed_metrics": sorted(m.value for m in allowed_metrics(strategy.task_type)) if uses_ai(strategy.necessity) else [],
        },
        "selected_dataset": input.dataset.name,
        "model_plan": [{"name": o.name, "use": o.use.value} for o in input.models.options],
        "technology_stack": [{"area": c.area.value, "choice": c.choice} for c in input.technology.stack],
    }
    if input.preference is not None and input.previous_plan is not None:
        llm_input["redesign"] = {
            "student_request": REDESIGN_REQUEST,
            "previous_answer": input.previous_plan.model_dump(mode="json"),
        }
    return llm_input


class DesignArchitectureSkill(Skill):
    metadata = SkillMetadata(
        name="design_architecture",
        description=(
            "Design the system architecture (components and data flows) and the evaluation plan "
            "(metrics, system tests, baseline) from the student's approved decisions."
        ),
        version="0.11.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: DesignArchitectureInput,
        on_progress: ArchitectureProgressCallback | None = None,
    ) -> DesignArchitectureOutput:
        """
        Design the technical plan.

        Raises:
            ArchitecturePlanRejectedError: the reply failed the checks twice.
            LLMError subclasses:           the gateway could not get an answer.
        """
        async def report(phase: ArchitecturePhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(ArchitectureProgress(phase=phase, label=label))

        llm_input = build_llm_input(input)
        rejections: Counter = Counter()
        first_label = REDESIGNING_LABEL if input.preference is not None else DESIGNING_LABEL
        for _ in range(MAX_ATTEMPTS):
            await report(ArchitecturePhase.DESIGNING, first_label)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMTechnicalPlanDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            await report(ArchitecturePhase.CHECKING, CHECKING_LABEL)
            plan, reason = check_plan_draft(result.output, input)
            if plan is not None:
                return DesignArchitectureOutput(
                    plan=plan, provider=result.provider, model=result.model,
                    prompt_version=PROMPT_VERSION, rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Use 4-10 components with unique ids and listed kinds; "
                "3-14 flows between existing ids; connect every component; include a user and an interface; a "
                "model component and 1-5 allowed_metrics only when uses_ai is true (none otherwise); 1-5 distinct "
                "tests; a baseline when baseline_comparison is used; technology only from the approved stack, "
                "dataset or model plan; no links; keep every text short."
            )}
        raise ArchitecturePlanRejectedError("The technical plan failed Grey's checks twice.", dict(rejections))
