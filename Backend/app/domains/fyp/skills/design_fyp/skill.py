"""
DesignFYPSkill — turns the student's chosen problem into a concrete,
student-sized FYP (product blueprint §17), or redesigns it when the student
asks for one of the controlled adjustments.

  LLMGateway (profile "structured_reasoning") — the ONE place the model is called
  check_design (code)                         — rejects replies that break the rules

If a reply fails the checks, the skill asks once more (naming the rule that
failed), then gives up with DesignRejectedError.

The design says WHAT the student builds and for whom. It never picks a
dataset, model, API or technology stack — those are later stages.

What the skill does NOT do (by design): write to or read the database (the
runner passes the problem and area in), count redesigns, or decide the next stage.
"""
from collections import Counter

from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.design_fyp import ADJUSTMENT_REQUESTS, INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.design_fyp.schemas import DesignFYPInput, DesignFYPOutput, LLMFYPDesignDraft
from app.domains.fyp.skills.design_fyp.validation import check_design
from app.domains.fyp.skills.fyp_design_shared import (
    DesignPhase,
    DesignProgress,
    ProgressCallback,
    brief_for_model,
)

MAX_ATTEMPTS = 2
# A short JSON reply plus the model's hidden reasoning; kept modest for Groq's
# free tier (about 8,000 tokens per minute).
MAX_OUTPUT_TOKENS = 3_000

DESIGNING_LABEL = "Designing a student-sized FYP"
REDESIGNING_LABEL = "Redesigning your FYP"
CHECKING_LABEL = "Checking the design against your problem"


class DesignRejectedError(Exception):
    """The model's design failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def build_llm_input(input: DesignFYPInput) -> dict:
    """What the model sees: the problem, its area and, for a redesign, the request."""
    llm_input: dict = {
        "industry": input.industry,
        "branch": input.branch,
        "functional_area": input.area.functional_area,
        "specific_area": input.area.specific_area,
        "problem": brief_for_model(input.problem),
    }
    if input.adjustment is not None and input.previous_design is not None:
        llm_input["redesign"] = {
            "requested_change": ADJUSTMENT_REQUESTS[input.adjustment],
            "student_note": input.note or None,
            "previous_design": input.previous_design.model_dump(mode="json"),
        }
    return llm_input


class DesignFYPSkill(Skill):
    metadata = SkillMetadata(
        name="design_fyp",
        description=(
            "Turn the student's chosen problem into a concrete, student-sized FYP design, "
            "or redesign it with one controlled adjustment."
        ),
        version="0.5.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: DesignFYPInput,
        on_progress: ProgressCallback | None = None,
    ) -> DesignFYPOutput:
        """
        Design (or redesign) the FYP.

        Raises:
            DesignRejectedError: the reply failed the checks twice.
            LLMError subclasses:  the gateway could not get an answer.
        """
        async def report(phase: DesignPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(DesignProgress(phase=phase, label=label))

        llm_input = build_llm_input(input)
        designing = REDESIGNING_LABEL if input.adjustment else DESIGNING_LABEL
        rejections: Counter = Counter()

        for _ in range(MAX_ATTEMPTS):
            await report(DesignPhase.DESIGNING_FYP, designing)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMFYPDesignDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))

            await report(DesignPhase.CHECKING_DESIGN, CHECKING_LABEL)
            design, reason = check_design(result.output, input)
            if design is not None:
                return DesignFYPOutput(
                    design=design,
                    provider=result.provider,
                    model=result.model,
                    prompt_version=PROMPT_VERSION,
                    rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            # Ask once more, naming the rule that failed (no reply text is echoed back).
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your design broke a rule: {reason}. Never name organizations, datasets, models, "
                "libraries, APIs or technologies, never include links, and keep every field short."
                + (" Make the redesign clearly different from the previous design." if reason == "unchanged" else "")
            )}

        raise DesignRejectedError("The FYP design failed Grey's checks twice.", dict(rejections))
