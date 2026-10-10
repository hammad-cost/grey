"""
Checks every model plan the model returns. Plain code — no AI.

  unknown_choice     — a kind or use that isn't on Grey's lists
  unknown_candidate  — a page number that isn't in the list
  empty              — a required text is empty
  wrong_count        — more than 3 options, or 0 / more than 4 limitations
  unsupported_fact   — a percentage that the page's own text doesn't state
  contains_url       — a link appears anywhere
  too_long           — a text is far longer than asked for
  same_model,
  repeated_model     — the rules in model_rules.py
"""
import re

from app.core.brain.model_rules import plan_rule_broken
from app.core.brain.schemas import (
    MAX_MODEL_OPTIONS,
    ModelCandidate,
    ModelKind,
    ModelOption,
    ModelPlan,
    ModelUse,
)
from app.domains.fyp.skills.find_models.schemas import FindModelsInput, LLMModelOptionDraft, LLMModelPlanDraft
from app.domains.fyp.skills.fyp_design_shared import contains_url

MAX_TEXT_CHARS = 500
MAX_ITEM_CHARS = 160
MAX_LIMITATIONS = 4

_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")


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


def _option(draft: LLMModelOptionDraft, candidates: list[ModelCandidate]) -> ModelOption:
    kind = _choice(draft.kind, ModelKind)
    use = _choice(draft.use, ModelUse)
    if not 1 <= draft.candidate_number <= len(candidates):
        raise _Rejected("unknown_candidate")
    page = candidates[draft.candidate_number - 1]
    name, reason, role = _clean(draft.name), _clean(draft.reason), _clean(draft.role)
    limitations = [_clean(item) for item in draft.limitations]
    if not name or not reason or not role or any(not item for item in limitations):
        raise _Rejected("empty")
    if not 1 <= len(limitations) <= MAX_LIMITATIONS:
        raise _Rejected("wrong_count")
    if any(len(t) > MAX_TEXT_CHARS for t in (name, reason, role)) or any(len(i) > MAX_ITEM_CHARS for i in limitations):
        raise _Rejected("too_long")
    page_text = f"{page.title} {page.snippet}".replace(" ", "")
    for percent in _PERCENT.findall(" ".join([reason, *limitations])):
        if percent.replace(" ", "") not in page_text:
            raise _Rejected("unsupported_fact")     # e.g. "95% accuracy" the page never states
    return ModelOption(
        kind=kind, name=name, source=page.publisher or "Unknown site", url=page.url,
        use=use, reason=reason, role=role, limitations=limitations,
    )


def check_plan_draft(
    draft: LLMModelPlanDraft, input: FindModelsInput, candidates: list[ModelCandidate]
) -> tuple[ModelPlan | None, str | None]:
    """Turn a draft into a ModelPlan, or return (None, the reason it was rejected)."""
    try:
        summary = _clean(draft.summary)
        if not summary:
            raise _Rejected("empty")
        if len(summary) > MAX_TEXT_CHARS:
            raise _Rejected("too_long")
        if len(draft.options) > MAX_MODEL_OPTIONS:
            raise _Rejected("wrong_count")
        plan = ModelPlan(needs_model=True, summary=summary, options=[_option(o, candidates) for o in draft.options])
    except _Rejected as rejected:
        return None, rejected.reason

    texts = [plan.summary]
    for option in plan.options:
        texts += [option.name, option.reason, option.role, *option.limitations]
    if any(contains_url(text) for text in texts):
        return None, "contains_url"

    broken = plan_rule_broken(
        plan, {c.url for c in candidates}, preference=input.preference, previous=input.previous_plan
    )
    if broken is not None:
        return None, broken
    return plan, None
