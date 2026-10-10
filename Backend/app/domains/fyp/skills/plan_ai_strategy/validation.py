"""
Checks every AI strategy the model returns. Plain code — no AI.

A draft becomes an AIStrategy only if it passes every check; otherwise the
first failing rule is returned and the skill asks once more.

  unknown_choice             — a verdict, task or approach that isn't on Grey's lists
  empty                      — a required text is empty
  wrong_count                — too few or too many non-AI components
  missing_ai_details,
  ai_details_without_ai,
  approach_mismatch,
  same_fallback              — the consistency rules in ai_strategy_rules.py
  contains_url               — a link appears anywhere
  too_long                   — a text is far longer than asked for
  names_organization         — an evidence organization is named
  names_specific_technology  — a named dataset, model, library, API, cloud service…
                               (the technical plan comes in later stages)
"""
from app.core.brain.ai_strategy_rules import strategy_rule_broken
from app.core.brain.schemas import AIApproach, AINecessity, AIStrategy, AITaskType, StrategyChoice
from app.domains.fyp.skills.fyp_design_shared import contains_url, named_technology, names_organization
from app.domains.fyp.skills.plan_ai_strategy.schemas import (
    NONE,
    LLMAIStrategyDraft,
    LLMStrategyChoiceDraft,
    PlanAIStrategyInput,
)

MAX_COMPONENT_CHARS = 120
MAX_TEXT_CHARS = 500          # same limit as the other FYP texts
MIN_COMPONENTS, MAX_COMPONENTS = 1, 6


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _clean(text: str) -> str:
    return " ".join(text.split())


def _choice(value: str, enum: type):
    """The enum member for `value`, None for "none", or rejected as unknown."""
    value = value.strip().lower()
    if value in ("", NONE):
        return None
    try:
        return enum(value)
    except ValueError:
        raise _Rejected("unknown_choice") from None


def _strategy_choice(draft: LLMStrategyChoiceDraft) -> StrategyChoice | None:
    approach = _choice(draft.approach, AIApproach)
    if approach is None:
        return None
    reason = _clean(draft.reason)
    if not reason:
        raise _Rejected("empty")
    return StrategyChoice(approach=approach, reason=reason)


def _build(draft: LLMAIStrategyDraft) -> AIStrategy:
    necessity = _choice(draft.necessity, AINecessity)
    if necessity is None:
        raise _Rejected("unknown_choice")
    task_type = _choice(draft.task_type, AITaskType)
    primary = _strategy_choice(draft.primary_strategy)
    fallback = _strategy_choice(draft.fallback_strategy)

    components = [_clean(c) for c in draft.non_ai_components]
    if not MIN_COMPONENTS <= len(components) <= MAX_COMPONENTS:
        raise _Rejected("wrong_count")
    reason, without_ai = _clean(draft.necessity_reason), _clean(draft.without_ai)
    if not reason or not without_ai or any(not c for c in components):
        raise _Rejected("empty")

    return AIStrategy(
        necessity=necessity,
        necessity_reason=reason,
        without_ai=without_ai,
        ai_component=_clean(draft.ai_component) or None,
        non_ai_components=components,
        task_type=task_type,
        primary_strategy=primary,
        fallback_strategy=fallback,
    )


def check_strategy_draft(
    draft: LLMAIStrategyDraft, input: PlanAIStrategyInput
) -> tuple[AIStrategy | None, str | None]:
    """Turn a draft into an AIStrategy, or return (None, the reason it was rejected)."""
    try:
        strategy = _build(draft)
    except _Rejected as rejected:
        return None, rejected.reason

    broken = strategy_rule_broken(strategy)
    if broken is not None:
        return None, broken

    choices = [c for c in (strategy.primary_strategy, strategy.fallback_strategy) if c is not None]
    texts = [strategy.necessity_reason, strategy.without_ai, *(c.reason for c in choices)]
    if strategy.ai_component:
        texts.append(strategy.ai_component)
    everything = texts + strategy.non_ai_components

    if any(contains_url(text) for text in everything):
        return None, "contains_url"
    if any(len(t) > MAX_TEXT_CHARS for t in texts) or any(
        len(c) > MAX_COMPONENT_CHARS for c in strategy.non_ai_components
    ):
        return None, "too_long"
    if any(names_organization(text, input.problem.organizations) for text in everything):
        return None, "names_organization"
    if any(named_technology(text) for text in everything):
        return None, "names_specific_technology"

    return strategy, None
