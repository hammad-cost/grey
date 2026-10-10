"""
FindModelsSkill — checks whether ready-made models, APIs or code already exist
for the student's AI task, and what the student should do with each one
(product blueprint §26, Release 0.9).

  search.py (code)          — targeted searches on model hubs, code sites and cloud AI pages
  LLMGateway                — the ONE place the model is called ("structured_reasoning"):
                              it chooses 0-3 pages by number and says how to use each
  check_plan_draft (code)   — rejects replies that break the rules

A project whose approved AI strategy uses no AI gets a code-built answer
("no model needed") without any search or model call — AI isn't needed for that.

What the skill does NOT do (by design): read or write the database, count
re-searches, or decide the next stage.
"""
from collections import Counter

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import ModelPlan, ModelPreference, ProjectDefinition, ScopeKind
from app.core.llm import STRUCTURED_REASONING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.core.tools.search import SearchProvider, SearchProviderError
from app.domains.fyp.prompts.find_models import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills.find_datasets.search import search_datasets
from app.domains.fyp.skills.find_models.schemas import (
    FindModelsInput,
    FindModelsOutput,
    LLMModelPlanDraft,
    ModelPhase,
    ModelProgress,
    ModelProgressCallback,
    ModelsUnavailableError,
)
from app.domains.fyp.skills.find_models.search import build_model_queries, is_model_page
from app.domains.fyp.skills.find_models.validation import check_plan_draft
from app.domains.fyp.skills.fyp_design_shared import brief_for_model

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 3_500

SEARCHING_LABEL = "Searching model hubs, code and AI services"
NO_AI_LABEL = "Checking your AI strategy"
CHOOSING_LABEL = "Choosing what could help your project"
CHECKING_LABEL = "Checking each option against your AI strategy"

# Who "made" the plan when no model was asked (saved on the run instead of a provider and model).
RULES_PROVIDER, RULES_MODEL, RULES_PROMPT = "grey", "rules", "none"

NO_AI_SUMMARY = (
    "Your approved AI strategy doesn't use AI, so no pretrained model or API is needed. "
    "You build the system with ordinary code."
)


class ModelPlanRejectedError(Exception):
    """The model's plan failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int], searches_used: int) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary
        self.searches_used = searches_used


def _core_features(definition: ProjectDefinition) -> list[str]:
    return [item.title for item in definition.scope if item.kind == ScopeKind.CORE]


def build_llm_input(input: FindModelsInput, candidates) -> dict:
    """What the model sees: the project, the AI strategy, the dataset and the numbered pages (no links)."""
    strategy = input.strategy
    llm_input: dict = {
        "industry": input.industry,
        "branch": input.branch,
        "functional_area": input.area.functional_area,
        "problem": brief_for_model(input.problem),
        "core_features": _core_features(input.definition),
        "ai_strategy": {
            "ai_component": strategy.ai_component or "",
            "task_type": strategy.task_type.value if strategy.task_type else "none",
            "primary_approach": strategy.primary_strategy.approach.value if strategy.primary_strategy else "none",
        },
        "selected_dataset": {"name": input.dataset.name, "kind": input.dataset.kind.value},
        "candidates": [
            {"number": n, "title": c.title, "site": c.publisher or "", "snippet": c.snippet}
            for n, c in enumerate(candidates, start=1)
        ],
    }
    if input.preference is not None and input.previous_plan is not None:
        llm_input["research"] = {
            "student_request": "Look for other models, APIs or code than the ones you showed before.",
            "previous_answer": [option.name for option in input.previous_plan.options],
        }
    return llm_input


class FindModelsSkill(Skill):
    metadata = SkillMetadata(
        name="find_models",
        description=(
            "Check whether pretrained models, APIs or code already exist for the student's AI task, "
            "and say whether to use each directly, fine-tune it, use it as a benchmark, or avoid it."
        ),
        version="0.9.0",
    )

    def __init__(self, search: SearchProvider, llm: LLMGateway, max_searches: int = 6) -> None:
        self._search = search
        self._llm = llm
        self._max_searches = max_searches

    async def execute(
        self,
        input: FindModelsInput,
        on_progress: ModelProgressCallback | None = None,
    ) -> FindModelsOutput:
        """
        Search, choose and check (or answer "no model needed" for a project without AI).

        Raises:
            ModelsUnavailableError: every search failed.
            ModelPlanRejectedError: the reply failed the checks twice.
            LLMError subclasses:    the gateway could not get an answer.
        """
        async def report(phase: ModelPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(ModelProgress(phase=phase, label=label))

        if not uses_ai(input.strategy.necessity):
            await report(ModelPhase.SEARCHING, NO_AI_LABEL)
            return FindModelsOutput(
                plan=ModelPlan(needs_model=False, summary=NO_AI_SUMMARY),
                candidates=[], searches_used=0,
                provider=RULES_PROVIDER, model=RULES_MODEL, prompt_version=RULES_PROMPT,
            )

        task = input.strategy.task_type.value if input.strategy.task_type else input.problem.task_type.value
        queries = build_model_queries(input.industry, input.branch, input.problem.title, task, input.preference)
        await report(ModelPhase.SEARCHING, SEARCHING_LABEL)
        shown = set()
        if input.preference == ModelPreference.OTHER_OPTIONS and input.previous_plan is not None:
            shown = {option.url for option in input.previous_plan.options}
        try:
            found = await search_datasets(
                self._search, queries, max_searches=self._max_searches,
                known=input.known_candidates, exclude_urls=shown, is_wanted=is_model_page,
            )
        except SearchProviderError as error:
            raise ModelsUnavailableError(
                f"Every model search failed ({type(error).__name__}).", searches_used=len(queries)
            ) from error
        candidates = found.candidates

        llm_input = build_llm_input(input, candidates)
        rejections: Counter = Counter()
        for _ in range(MAX_ATTEMPTS):
            await report(ModelPhase.CHOOSING, CHOOSING_LABEL)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=STRUCTURED_REASONING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMModelPlanDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            await report(ModelPhase.CHECKING, CHECKING_LABEL)
            plan, reason = check_plan_draft(result.output, input, candidates)
            if plan is not None:
                return FindModelsOutput(
                    plan=plan, candidates=candidates, searches_used=found.searches_used,
                    provider=result.provider, model=result.model, prompt_version=PROMPT_VERSION,
                    rejection_summary=dict(rejections),
                )
            rejections[reason] += 1
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Choose 0-3 listed candidate numbers, each once; kind is "
                "pretrained_model, api_service or code_repository; use is use_directly, fine_tune, benchmark or "
                "avoid; 1-4 limitations; never state numbers the snippet doesn't give; never include links; "
                "keep every text short."
            )}

        raise ModelPlanRejectedError(
            "The model plan failed Grey's checks twice.", dict(rejections), found.searches_used
        )
