"""
What the student sees about the AI necessity check and strategy (Release 0.7),
built from the Project Brain.

Which re-checks are offered is decided here, by the same rules the Brain
uses, so the frontend never has to guess (e.g. "Can I do this without AI?"
is not offered when the project already works without AI).
"""
from pydantic import BaseModel

from app.core.brain.ai_strategy_rules import recheck_problem, uses_ai
from app.core.brain.schemas import (
    MAX_AI_STRATEGY_RECHECKS,
    AIStrategyPreference,
    AIStrategyStatus,
    ProjectDefinitionStatus,
    ScopeKind,
    StoredAIStrategy,
    WorkspaceBrainSnapshot,
)


class AIStrategyView(BaseModel):
    """Everything the AI strategy cards need, in one piece."""
    fyp_title: str
    core_features: list[str]                       # the approved core scope, by title
    strategy: StoredAIStrategy | None = None
    uses_ai: bool | None = None                    # None until Grey has checked
    rechecks_left: int = MAX_AI_STRATEGY_RECHECKS
    max_rechecks: int = MAX_AI_STRATEGY_RECHECKS
    available_rechecks: list[AIStrategyPreference] = []   # what the student may ask for right now


def _available_rechecks(strategy: StoredAIStrategy | None) -> list[AIStrategyPreference]:
    if strategy is None or strategy.status != AIStrategyStatus.DRAFT:
        return []
    if strategy.rechecks_used >= MAX_AI_STRATEGY_RECHECKS:
        return []
    return [p for p in AIStrategyPreference if recheck_problem(strategy.strategy, p) is None]


def build_ai_strategy_view(snapshot: WorkspaceBrainSnapshot) -> AIStrategyView | None:
    """The AI strategy view for a project, or None until the scope is approved."""
    design = snapshot.fyp_design
    definition = snapshot.project_definition
    if design is None or definition is None or definition.status != ProjectDefinitionStatus.APPROVED:
        return None
    strategy = snapshot.ai_strategy
    return AIStrategyView(
        fyp_title=design.title,
        core_features=[item.title for item in definition.scope if item.kind == ScopeKind.CORE],
        strategy=strategy,
        uses_ai=uses_ai(strategy.strategy.necessity) if strategy else None,
        rechecks_left=max(0, MAX_AI_STRATEGY_RECHECKS - strategy.rechecks_used) if strategy else MAX_AI_STRATEGY_RECHECKS,
        available_rechecks=_available_rechecks(strategy),
    )
