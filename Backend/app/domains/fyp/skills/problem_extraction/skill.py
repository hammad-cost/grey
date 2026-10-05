"""
ProblemExtractionSkill — turns a project's evidence into 3–5 real problem
opportunities (product blueprint §12–14).

Responsibilities are kept apart:
  EvidenceReader (repository)  — loads the facts: evidence saved by research
  build_context (code)         — chooses and shortens what the model sees
  LLMGateway                   — the ONE place the model is called,
                                 with profile "structured_reasoning"
  select_candidates (code)     — rejects ungrounded or invalid drafts,
                                 merges duplicates, ranks, keeps the top 5

If fewer than 3 problems survive, the skill asks the model once more (telling
it what went wrong), then gives up with TooFewProblemsError. It never pads
the list with invented problems.

What the skill does NOT do (by design):
  - write to the database (the workflow runner saves the result)
  - search the web (it only uses evidence that research already stored)
  - pick a provider or model (the gateway does, from the profile)
  - decide the next workflow stage
"""
from collections import Counter
from collections.abc import Awaitable, Callable

from app.core.brain.readers import EvidenceReader
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest, LLMResult
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.problem_extraction import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.problem_extraction.context import build_context
from app.domains.fyp.skills.problem_extraction.schemas import (
    LLMProblemDrafts,
    ProblemExtractionInput,
    ProblemExtractionOutput,
    ProblemPhase,
    ProblemProgress,
)
from app.domains.fyp.skills.problem_extraction.validation import select_candidates

MIN_PROBLEMS = 3
MAX_ATTEMPTS = 2
# Output budget for one reply (drafts + the model's reasoning). Kept modest
# because Groq's free tier counts it toward 8,000 tokens per minute.
MAX_OUTPUT_TOKENS = 4_000

ProgressCallback = Callable[[ProblemProgress], Awaitable[None]]

LABELS = {
    ProblemPhase.REVIEWING_EVIDENCE: "Reviewing your evidence",
    ProblemPhase.IDENTIFYING_PROBLEMS: "Identifying real problems organizations face",
    ProblemPhase.CHECKING_PROBLEMS: "Checking each problem against its sources",
}


class TooFewProblemsError(Exception):
    """Fewer than MIN_PROBLEMS problems passed validation, even after a second attempt."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


class ProblemExtractionSkill(Skill):
    metadata = SkillMetadata(
        name="problem_extraction",
        description=(
            "Turn a project's stored evidence into 3–5 evidence-backed, student-sized "
            "real-world problem opportunities."
        ),
        version="0.3.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def execute(
        self,
        input: ProblemExtractionInput,
        evidence: EvidenceReader,
        on_progress: ProgressCallback | None = None,
    ) -> ProblemExtractionOutput:
        """
        Find problem opportunities for the project.

        Raises:
            NotEnoughEvidenceError: too little usable evidence (the model is not called).
            TooFewProblemsError:    fewer than 3 valid problems after two attempts.
            LLMError subclasses:    the gateway could not get an answer (e.g. LLMUnavailable, LLMRefusal).
        """
        async def report(phase: ProblemPhase) -> None:
            if on_progress is not None:
                await on_progress(ProblemProgress(phase=phase, label=LABELS[phase]))

        await report(ProblemPhase.REVIEWING_EVIDENCE)
        stored = await evidence.list_evidence(input.workspace_id)
        context = build_context(input.industry, input.branch, stored)

        rejections: Counter = Counter()
        generated = 0
        llm_input = dict(context.llm_input)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            await report(ProblemPhase.IDENTIFYING_PROBLEMS)
            result: LLMResult[LLMProblemDrafts] = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMProblemDrafts,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            generated += len(result.output.problems)

            await report(ProblemPhase.CHECKING_PROBLEMS)
            attempt_rejections: Counter = Counter()
            candidates = select_candidates(result.output.problems, context.sources_by_ref, attempt_rejections)
            rejections.update(attempt_rejections)

            if len(candidates) >= MIN_PROBLEMS:
                return ProblemExtractionOutput(
                    candidates=candidates,
                    provider=result.provider,
                    model=result.model,
                    prompt_version=PROMPT_VERSION,
                    candidates_generated=generated,
                    rejection_summary=dict(rejections),
                )

            # Ask once more, saying what went wrong (reasons only — no evidence text).
            reasons = ", ".join(f"{reason} ×{count}" for reason, count in attempt_rejections.most_common())
            llm_input = {
                **context.llm_input,
                "feedback_from_previous_attempt": (
                    f"Only {len(candidates)} of your problems passed Grey's checks"
                    + (f" (rejected: {reasons})" if reasons else "")
                    + ". Cite only the refs given, reuse each source's own wording in supporting_point, "
                      "include a Tier A or B source for every problem, and never name an organization "
                      "in a title or FYP direction."
                ),
            }

        raise TooFewProblemsError(
            f"Fewer than {MIN_PROBLEMS} problems passed validation after {MAX_ATTEMPTS} attempts.",
            rejection_summary=dict(rejections),
        )
