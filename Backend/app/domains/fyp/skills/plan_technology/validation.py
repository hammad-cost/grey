"""
Checks every technology plan the model returns. Plain code — no AI.

  unknown_choice   — an area, hardware kind or cost that isn't on Grey's lists
  empty            — a required text is empty
  wrong_count      — 2-6 stack choices, 1-5 hardware items
  too_long         — a text is far longer than asked for
  contains_url     — a link appears anywhere
  option_list      — a "choice" lists several options ("React or Vue") instead of deciding
  duplicate_area, missing_ai_ml, ai_without_ai, no_application,
  missing_alternative — the rules in technology_rules.py
"""
import re

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import (
    CostLevel,
    HardwareItem,
    HardwareKind,
    StackArea,
    StackChoice,
    TechnologyPlan,
)
from app.core.brain.technology_rules import plan_rule_broken
from app.domains.fyp.skills.fyp_design_shared import contains_url
from app.domains.fyp.skills.plan_technology.schemas import LLMTechnologyPlanDraft, PlanTechnologyInput

MAX_CHOICE_CHARS = 60
MAX_TEXT_CHARS = 400
STACK_COUNT = (2, 6)
HARDWARE_COUNT = (1, 5)

# "React or Vue", "React / Vue", "React, Vue, Angular" — a list of options, not a decision.
_OPTION_LIST = re.compile(r"\bor\b|/|,", re.IGNORECASE)


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _clean(text: str) -> str:
    return " ".join(text.split())


def _choice(value: str, enum: type):
    try:
        return enum(value.strip().lower())
    except ValueError:
        raise _Rejected("unknown_choice") from None


def _text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    text = _clean(value)
    if not text:
        raise _Rejected("empty")
    if len(text) > limit:
        raise _Rejected("too_long")
    return text


def _build(draft: LLMTechnologyPlanDraft) -> TechnologyPlan:
    if not STACK_COUNT[0] <= len(draft.stack) <= STACK_COUNT[1]:
        raise _Rejected("wrong_count")
    if not HARDWARE_COUNT[0] <= len(draft.hardware) <= HARDWARE_COUNT[1]:
        raise _Rejected("wrong_count")
    stack = []
    for item in draft.stack:
        choice = _text(item.choice, MAX_CHOICE_CHARS)
        if _OPTION_LIST.search(choice):
            raise _Rejected("option_list")
        stack.append(StackChoice(area=_choice(item.area, StackArea), choice=choice, reason=_text(item.reason)))
    hardware = [
        HardwareItem(
            kind=_choice(item.kind, HardwareKind),
            name=_text(item.name, MAX_CHOICE_CHARS * 2),
            purpose=_text(item.purpose),
            essential=item.essential,
            cost=_choice(item.cost, CostLevel),
            alternative=_clean(item.alternative) or None,
        )
        for item in draft.hardware
    ]
    return TechnologyPlan(summary=_text(draft.summary), stack=stack, hardware=hardware)


def check_plan_draft(draft: LLMTechnologyPlanDraft, input: PlanTechnologyInput) -> tuple[TechnologyPlan | None, str | None]:
    """Turn a draft into a TechnologyPlan, or return (None, the reason it was rejected)."""
    try:
        plan = _build(draft)
    except _Rejected as rejected:
        return None, rejected.reason
    texts = [plan.summary]
    for c in plan.stack:
        texts += [c.choice, c.reason]
    for h in plan.hardware:
        texts += [h.name, h.purpose, h.alternative or ""]
    if any(len(t) > MAX_TEXT_CHARS for t in texts):
        return None, "too_long"
    if any(contains_url(t) for t in texts):
        return None, "contains_url"
    broken = plan_rule_broken(plan, uses_ai=uses_ai(input.strategy.necessity))
    if broken is not None:
        return None, broken
    return plan, None
