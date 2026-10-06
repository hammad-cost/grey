"""
ClassifyAreaSkill — decides where the student's chosen problem sits
(product blueprint §16): Industry → Branch → Functional Area → Specific Area.

The student is never asked for this; Grey works it out after the problem
becomes meaningful.

  LLMGateway (profile "fast_cheap") — the ONE place the model is called
  check_area (code)                 — rejects replies that break the rules

If the reply fails the checks, the skill asks once more (saying which rule
failed), then gives up with AreaRejectedError.

What the skill does NOT do (by design): write to the database, read the
database (the runner passes the problem in), or decide the next stage.
"""
from collections import Counter

from app.core.brain.schemas import FunctionalArea
from app.core.llm import FAST_CHEAP, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.classify_area import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.classify_area.schemas import ClassifyAreaInput, ClassifyAreaOutput, LLMAreaDraft
from app.domains.fyp.skills.fyp_design_shared import (
    DesignPhase,
    DesignProgress,
    ProgressCallback,
    brief_for_model,
    contains_url,
    named_technology,
    names_organization,
)

MAX_ATTEMPTS = 2
# Small: a short JSON reply plus the model's hidden reasoning.
MAX_OUTPUT_TOKENS = 1_500
MAX_AREA_CHARS = 80
MAX_EXPLANATION_CHARS = 300

LABEL = "Finding where your project fits"


class AreaRejectedError(Exception):
    """The model's area failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def check_area(draft: LLMAreaDraft, input: ClassifyAreaInput) -> tuple[FunctionalArea | None, str | None]:
    """Turn a draft into a FunctionalArea, or return (None, the reason it was rejected)."""
    functional = " ".join(draft.functional_area.split())
    specific = " ".join(draft.specific_area.split())
    explanation = " ".join(draft.explanation.split())
    texts = (functional, specific, explanation)

    if not functional or not specific or not explanation:
        return None, "empty"
    if any(contains_url(t) for t in texts):
        return None, "contains_url"
    if len(functional) > MAX_AREA_CHARS or len(specific) > MAX_AREA_CHARS or len(explanation) > MAX_EXPLANATION_CHARS:
        return None, "too_long"
    if functional.lower() in (input.industry.lower(), input.branch.lower()):
        return None, "same_as_branch"
    if specific.lower() == functional.lower():
        return None, "specific_same_as_functional"
    if any(named_technology(t) for t in texts):
        return None, "names_specific_technology"
    if any(names_organization(t, input.problem.organizations) for t in texts):
        return None, "names_organization"
    return FunctionalArea(functional_area=functional, specific_area=specific, explanation=explanation), None


class ClassifyAreaSkill(Skill):
    metadata = SkillMetadata(
        name="classify_area",
        description="Decide the functional area and specific area of the student's chosen problem.",
        version="0.5.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: ClassifyAreaInput,
        on_progress: ProgressCallback | None = None,
    ) -> ClassifyAreaOutput:
        """
        Classify the problem.

        Raises:
            AreaRejectedError:  the reply failed the checks twice.
            LLMError subclasses: the gateway could not get an answer.
        """
        if on_progress is not None:
            await on_progress(DesignProgress(phase=DesignPhase.CLASSIFYING_AREA, label=LABEL))

        llm_input: dict = {
            "industry": input.industry,
            "branch": input.branch,
            "problem": brief_for_model(input.problem),
        }
        rejections: Counter = Counter()

        for _ in range(MAX_ATTEMPTS):
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=FAST_CHEAP,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMAreaDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            area, reason = check_area(result.output, input)
            if area is not None:
                return ClassifyAreaOutput(
                    area=area, provider=result.provider, model=result.model, prompt_version=PROMPT_VERSION,
                )
            rejections[reason] += 1
            # Ask once more, naming the rule that failed (no reply text is echoed back).
            llm_input = {**llm_input, "feedback_from_previous_attempt": f"Your answer broke a rule: {reason}."}

        raise AreaRejectedError("The functional area failed Grey's checks twice.", dict(rejections))
