"""
Technology rules (Release 0.10) — plain code, no AI.

One place decides whether a technology plan is consistent, so the skill, the
workflow and the Project Brain apply the same rules:

  - one choice per area (decisions, not option lists — blueprint §28)
  - a project that uses AI has an AI / ML choice; one that doesn't has no
    AI / ML and no training choice
  - there is a frontend or a backend, so the project can be demonstrated
  - a high-cost hardware item names a cheaper alternative
"""
from app.core.brain.schemas import CostLevel, StackArea, TechnologyPlan


class TechnologyRuleError(ValueError):
    """The plan breaks a rule."""


def plan_rule_broken(plan: TechnologyPlan, *, uses_ai: bool) -> str | None:
    """The first rule the plan breaks (a short code), or None if it is consistent."""
    areas = [choice.area for choice in plan.stack]
    if len(set(areas)) != len(areas):
        return "duplicate_area"
    if uses_ai and StackArea.AI_ML not in areas:
        return "missing_ai_ml"
    if not uses_ai and (StackArea.AI_ML in areas or StackArea.TRAINING in areas):
        return "ai_without_ai"
    if StackArea.FRONTEND not in areas and StackArea.BACKEND not in areas:
        return "no_application"
    if any(item.cost == CostLevel.HIGH and not item.alternative for item in plan.hardware):
        return "missing_alternative"
    return None


def check_plan(plan: TechnologyPlan, *, uses_ai: bool) -> None:
    """Raise TechnologyRuleError if the plan breaks a rule."""
    broken = plan_rule_broken(plan, uses_ai=uses_ai)
    if broken is not None:
        raise TechnologyRuleError(f"The technology plan breaks a rule ({broken}).")
