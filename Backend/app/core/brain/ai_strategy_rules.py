"""
AI strategy rules (Release 0.7) — plain code, no AI.

One place decides whether an AI strategy is consistent and whether a re-check
the student asks for makes sense, so the skill, the workflow and the Project
Brain always apply the same rules:

  - a verdict that uses AI names the AI part, the task and a primary approach
  - a verdict without AI names none of them
  - "traditional ML" means training a model (or a hybrid), never generative AI
  - "an existing model or API is sufficient" means using one, not training one
  - the fallback approach differs from the primary one
"""
from app.core.brain.schemas import (
    AIApproach,
    AINecessity,
    AIStrategy,
    AIStrategyPreference,
    AITaskType,
)

# Verdicts where the project uses AI or machine learning.
USES_AI = {
    AINecessity.AI_NECESSARY,
    AINecessity.AI_OPTIONAL,
    AINecessity.TRADITIONAL_ML,
    AINecessity.EXISTING_MODEL,
}

# Approaches allowed as the primary one for some verdicts (the others allow any).
PRIMARY_APPROACHES = {
    AINecessity.TRADITIONAL_ML: {AIApproach.TRAIN_MODEL, AIApproach.HYBRID},
    AINecessity.EXISTING_MODEL: {AIApproach.PRETRAINED_MODEL, AIApproach.USE_API},
}

# Approaches that reuse something ready-made instead of building a model.
READY_MADE = {AIApproach.PRETRAINED_MODEL, AIApproach.USE_API}


class AIStrategyRuleError(ValueError):
    """The strategy, or the re-check the student asked for, breaks a rule."""


def uses_ai(necessity: AINecessity) -> bool:
    return necessity in USES_AI


def strategy_rule_broken(strategy: AIStrategy) -> str | None:
    """The first rule the strategy breaks (a short code), or None if it is consistent."""
    primary = strategy.primary_strategy
    fallback = strategy.fallback_strategy

    if not uses_ai(strategy.necessity):
        if strategy.ai_component or strategy.task_type or primary or fallback:
            return "ai_details_without_ai"
        return None

    if not strategy.ai_component or strategy.task_type is None or primary is None:
        return "missing_ai_details"
    allowed = PRIMARY_APPROACHES.get(strategy.necessity)
    if allowed is not None and primary.approach not in allowed:
        return "approach_mismatch"
    if strategy.necessity == AINecessity.TRADITIONAL_ML and strategy.task_type == AITaskType.GENERATIVE_AI:
        return "approach_mismatch"
    if fallback is not None and fallback.approach == primary.approach:
        return "same_fallback"
    return None


def check_strategy(strategy: AIStrategy) -> None:
    """Raise AIStrategyRuleError if the strategy breaks a rule."""
    broken = strategy_rule_broken(strategy)
    if broken is not None:
        raise AIStrategyRuleError(f"The AI strategy is not consistent ({broken}).")


def recheck_problem(strategy: AIStrategy, preference: AIStrategyPreference) -> str | None:
    """Why this re-check makes no sense for the current strategy (a message), or None if it is fine."""
    if not uses_ai(strategy.necessity):
        if preference == AIStrategyPreference.WITHOUT_AI:
            return "Your project already works without AI."
        return "Your project doesn't use AI, so there is no model to replace."
    if preference == AIStrategyPreference.EXISTING_MODEL and (
        strategy.necessity == AINecessity.EXISTING_MODEL
        or (strategy.primary_strategy is not None and strategy.primary_strategy.approach in READY_MADE)
    ):
        return "Your project already uses a ready-made model or service."
    return None
