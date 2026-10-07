"""
DefineProjectSkill — writes the problem definition, scope and proposed solution
for the student's approved FYP (product blueprint §19–21, Release 0.6).

  LLMGateway (profile "structured_reasoning") — the ONE place the model is called
  check_definition (code)                     — rejects replies that break the rules

If a reply fails the checks, the skill asks once more (naming the rule that
failed), then gives up with DefinitionRejectedError.

The definition says WHAT the system does. It never picks a dataset, model,
API or technology stack, and never decides whether AI is needed — those are
later stages.

What the skill does NOT do (by design): read or write the database (the
runner passes everything in), apply the student's scope changes, or decide
the next stage.
"""
from collections import Counter

from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.define_project import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.define_project.schemas import (
    DefineProjectInput,
    DefineProjectOutput,
    DefinitionPhase,
    DefinitionProgress,
    DefinitionProgressCallback,
    LLMProjectDefinitionDraft,
)
from app.domains.fyp.skills.define_project.validation import check_definition
from app.domains.fyp.skills.fyp_design_shared import brief_for_model

MAX_ATTEMPTS = 2
# A longer JSON reply than the design, plus the model's hidden reasoning; kept
# within Groq's free tier (about 8,000 tokens per minute).
MAX_OUTPUT_TOKENS = 4_000

DEFINING_LABEL = "Writing your problem definition, scope and solution"
CHECKING_LABEL = "Checking the definition against your FYP"


class DefinitionRejectedError(Exception):
    """The model's definition failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def build_llm_input(input: DefineProjectInput) -> dict:
    """What the model sees: the problem, its area and the approved design (no ids, links or organizations)."""
    return {
        "industry": input.industry,
        "branch": input.branch,
        "functional_area": input.area.functional_area,
        "specific_area": input.area.specific_area,
        "problem": brief_for_model(input.problem),
        "approved_design": input.design.model_dump(mode="json"),
    }


class DefineProjectSkill(Skill):
    metadata = SkillMetadata(
        name="define_project",
        description=(
            "Write the problem definition, the scope (core, optional, out of scope) and the "
            "proposed solution for the student's approved FYP."
        ),
        version="0.6.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: DefineProjectInput,
        on_progress: DefinitionProgressCallback | None = None,
    ) -> DefineProjectOutput:
        """
        Define the project.

        Raises:
            DefinitionRejectedError: the reply failed the checks twice.
            LLMError subclasses:      the gateway could not get an answer.
        """
        async def report(phase: DefinitionPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(DefinitionProgress(phase=phase, label=label))

        llm_input = build_llm_input(input)
        rejections: Counter = Counter()

        for _ in range(MAX_ATTEMPTS):
            await report(DefinitionPhase.DEFINING_PROJECT, DEFINING_LABEL)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMProjectDefinitionDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))

            await report(DefinitionPhase.CHECKING_DEFINITION, CHECKING_LABEL)
            definition, reason = check_definition(result.output, input)
            if definition is not None:
                return DefineProjectOutput(
                    definition=definition,
                    provider=result.provider,
                    model=result.model,
                    prompt_version=PROMPT_VERSION,
                    rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            # Ask once more, naming the rule that failed (no reply text is echoed back).
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your definition broke a rule: {reason}. Keep the list sizes asked for, give every feature "
                "a different short title, never name organizations, datasets, models, libraries, APIs or "
                "technologies, never include links, and keep every text short."
            )}

        raise DefinitionRejectedError("The project definition failed Grey's checks twice.", dict(rejections))
