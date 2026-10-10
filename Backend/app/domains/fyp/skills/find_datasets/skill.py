"""
FindDatasetsSkill — finds data for the student's approved project and
recommends a primary dataset and an alternative (product blueprint §24–25,
Release 0.8).

  search.py (code)             — targeted searches on dataset sites; keeps only dataset pages
  LLMGateway                   — the ONE place the model is called ("structured_reasoning"):
                                 it chooses two options from the numbered pages
  check_plan_draft (code)      — rejects replies that break the rules (invented facts,
                                 a page that wasn't found, the same dataset twice…)

If a reply fails the checks, the skill asks once more (naming the rule that
failed), then gives up with DatasetPlanRejectedError.

Grey only recommends public datasets the search really found. When none fits,
it recommends data the student creates or collects instead.

What the skill does NOT do (by design): read or write the database (the
runner passes everything in), count re-searches, or decide the next stage.
"""
from collections import Counter

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import DatasetPreference, ProjectDefinition, ScopeKind
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.core.tools.search import SearchProvider, SearchProviderError
from app.domains.fyp.prompts.find_datasets import INSTRUCTIONS, PREFERENCE_REQUESTS, PROMPT_VERSION
from app.domains.fyp.skills.find_datasets.schemas import (
    DatasetPhase,
    DatasetProgress,
    DatasetProgressCallback,
    DatasetsUnavailableError,
    FindDatasetsInput,
    FindDatasetsOutput,
    LLMDatasetPlanDraft,
)
from app.domains.fyp.skills.find_datasets.search import build_dataset_queries, search_datasets
from app.domains.fyp.skills.find_datasets.validation import check_plan_draft
from app.domains.fyp.skills.fyp_design_shared import brief_for_model

MAX_ATTEMPTS = 2
# Two options with their details plus the model's hidden reasoning; kept modest
# for Groq's free tier (about 8,000 tokens per minute).
MAX_OUTPUT_TOKENS = 4_000

SEARCHING_LABEL = "Searching dataset sites"
REUSING_LABEL = "Looking at the datasets found before"
CHOOSING_LABEL = "Choosing the two best options for your project"
CHECKING_LABEL = "Checking each dataset really fits your problem"


class DatasetPlanRejectedError(Exception):
    """The model's dataset recommendation failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int], searches_used: int) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary
        self.searches_used = searches_used


def search_task(input: FindDatasetsInput) -> str:
    """The task the searches are about: the AI task, or the problem's own task when AI isn't used."""
    if input.strategy.task_type is not None:
        return input.strategy.task_type.value
    return input.problem.task_type.value


def _core_features(definition: ProjectDefinition) -> list[dict]:
    return [
        {"title": item.title, "description": item.description}
        for item in definition.scope if item.kind == ScopeKind.CORE
    ]


def build_llm_input(input: FindDatasetsInput, candidates) -> dict:
    """What the model sees: the project, the AI strategy and the numbered pages (no links or ids)."""
    strategy = input.strategy
    llm_input: dict = {
        "industry": input.industry,
        "branch": input.branch,
        "functional_area": input.area.functional_area,
        "specific_area": input.area.specific_area,
        "problem": brief_for_model(input.problem),
        "core_features": _core_features(input.definition),
        "ai_strategy": {
            "uses_ai": uses_ai(strategy.necessity),
            "necessity": strategy.necessity.value,
            "ai_component": strategy.ai_component or "",
            "task_type": strategy.task_type.value if strategy.task_type else "none",
            "primary_approach": strategy.primary_strategy.approach.value if strategy.primary_strategy else "none",
        },
        "candidates": [
            {"number": n, "title": c.title, "site": c.publisher or "", "snippet": c.snippet}
            for n, c in enumerate(candidates, start=1)
        ],
    }
    if input.preference is not None and input.previous_plan is not None:
        previous = input.previous_plan
        llm_input["research"] = {
            "student_request": PREFERENCE_REQUESTS[input.preference.value],
            "previous_answer": {"primary": previous.primary.name, "alternative": previous.alternative.name},
        }
    return llm_input


class FindDatasetsSkill(Skill):
    metadata = SkillMetadata(
        name="find_datasets",
        description=(
            "Search dataset sites for data that fits the student's approved project and recommend "
            "one primary dataset and one alternative, with the details a student needs to judge them."
        ),
        version="0.8.0",
    )

    def __init__(self, search: SearchProvider, llm: LLMGateway, max_searches: int = 6) -> None:
        self._search = search
        self._llm = llm
        self._max_searches = max_searches

    async def execute(
        self,
        input: FindDatasetsInput,
        on_progress: DatasetProgressCallback | None = None,
    ) -> FindDatasetsOutput:
        """
        Search, choose and check.

        Raises:
            DatasetsUnavailableError: every search failed (nothing to choose from).
            DatasetPlanRejectedError: the reply failed the checks twice.
            LLMError subclasses:      the gateway could not get an answer.
        """
        async def report(phase: DatasetPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(DatasetProgress(phase=phase, label=label))

        # 1. Search (none for "own data": the pages found before are reused).
        queries = build_dataset_queries(
            input.industry, input.branch, input.problem.title, search_task(input), input.preference
        )
        await report(DatasetPhase.SEARCHING, SEARCHING_LABEL if queries else REUSING_LABEL)
        shown = set()
        if input.preference == DatasetPreference.OTHER_OPTIONS and input.previous_plan is not None:
            shown = {o.url for o in (input.previous_plan.primary, input.previous_plan.alternative) if o.url}
        try:
            found = await search_datasets(
                self._search,
                queries,
                max_searches=self._max_searches,
                known=input.known_candidates,
                exclude_urls=shown,
            )
        except SearchProviderError as error:
            raise DatasetsUnavailableError(
                f"Every dataset search failed ({type(error).__name__}).", searches_used=len(queries)
            ) from error
        candidates = found.candidates

        # 2. Choose, then 3. check (ask once more if the checks fail).
        llm_input = build_llm_input(input, candidates)
        rejections: Counter = Counter()
        for _ in range(MAX_ATTEMPTS):
            await report(DatasetPhase.CHOOSING, CHOOSING_LABEL)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMDatasetPlanDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))

            await report(DatasetPhase.CHECKING, CHECKING_LABEL)
            plan, reason = check_plan_draft(result.output, input, candidates)
            if plan is not None:
                return FindDatasetsOutput(
                    plan=plan,
                    candidates=candidates,
                    searches_used=found.searches_used,
                    provider=result.provider,
                    model=result.model,
                    prompt_version=PROMPT_VERSION,
                    rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            # Ask once more, naming the rule that failed (no reply text is echoed back).
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Use kind public (with a listed candidate_number), "
                "synthetic or student_collected (candidate_number 0, with how_to_get); fit good or partial; "
                "the two options must differ; copy size numbers and licenses only from the snippet, otherwise "
                "write 'Not stated — check the dataset page'; if the student asked for their own data, the "
                "primary must be synthetic or student_collected; never include links; keep every text short."
            )}

        raise DatasetPlanRejectedError(
            "The dataset recommendation failed Grey's checks twice.", dict(rejections), found.searches_used
        )
