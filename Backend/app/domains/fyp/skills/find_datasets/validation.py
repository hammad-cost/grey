"""
Checks every dataset recommendation the model returns. Plain code — no AI.

A draft becomes a DatasetPlan only if it passes every check; otherwise the
first failing rule is returned and the skill asks once more.

  unknown_choice     — a kind or fit that isn't on Grey's lists
  unknown_candidate  — a public dataset whose number isn't one of the candidates
  empty              — a required text is empty
  wrong_count        — too few or too many features, steps or limitations
  unsupported_fact   — a size number or a license that the page's own text doesn't state
  contains_url       — a link appears anywhere
  too_long           — a text is far longer than asked for
  missing_how_to_get,
  same_dataset,
  own_data_not_primary,
  repeated_dataset   — the rules in dataset_rules.py
"""
import re

from app.core.brain.dataset_rules import plan_rule_broken
from app.core.brain.schemas import (
    NOT_STATED,
    DatasetCandidate,
    DatasetFit,
    DatasetKind,
    DatasetOption,
    DatasetPlan,
)
from app.domains.fyp.skills.find_datasets.schemas import (
    FindDatasetsInput,
    LLMDatasetOptionDraft,
    LLMDatasetPlanDraft,
)
from app.domains.fyp.skills.fyp_design_shared import contains_url

OWN_DATA_SOURCE = "You"
MAX_TEXT_CHARS = 500
MAX_ITEM_CHARS = 160
COUNTS = {"main_features": (1, 8), "preprocessing": (1, 6), "limitations": (1, 5)}

_NUMBER = re.compile(r"\d[\d,.]*")


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _clean(text: str) -> str:
    return " ".join(text.split())


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _not_stated(text: str) -> bool:
    return _normalized(text).startswith("not stated") or _normalized(text) in ("unknown", "not available", "")


def _numbers(text: str) -> set[str]:
    return {n.strip(".,").replace(",", "") for n in _NUMBER.findall(text)}


def _supported(value: str, page_text: str, *, check_words: bool) -> str:
    """The value if the page text supports it, NOT_STATED if the model said so; otherwise rejected."""
    if _not_stated(value):
        return NOT_STATED
    if not _numbers(value) <= _numbers(page_text):
        raise _Rejected("unsupported_fact")          # e.g. "50,000 records" when the snippet has no 50000
    if check_words and _normalized(value) not in _normalized(page_text):
        raise _Rejected("unsupported_fact")          # a license must be copied from the page
    return value


def _items(values: list[str], field: str) -> list[str]:
    items = [_clean(v) for v in values]
    low, high = COUNTS[field]
    if not low <= len(items) <= high:
        raise _Rejected("wrong_count")
    if any(not item for item in items):
        raise _Rejected("empty")
    if any(len(item) > MAX_ITEM_CHARS for item in items):
        raise _Rejected("too_long")
    return items


def _choice(value: str, enum: type):
    try:
        return enum(value.strip().lower())
    except ValueError:
        raise _Rejected("unknown_choice") from None


def _option(draft: LLMDatasetOptionDraft, candidates: list[DatasetCandidate]) -> DatasetOption:
    kind = _choice(draft.kind, DatasetKind)
    fit = _choice(draft.fit, DatasetFit)
    name, relevance = _clean(draft.name), _clean(draft.relevance)
    size, labels, license_ = _clean(draft.size), _clean(draft.labels), _clean(draft.license)
    how_to_get = _clean(draft.how_to_get)
    if not name or not relevance or not size or not labels or not license_:
        raise _Rejected("empty")
    if any(len(t) > MAX_TEXT_CHARS for t in (name, relevance, size, labels, license_, how_to_get)):
        raise _Rejected("too_long")
    lists = {field: _items(getattr(draft, field), field) for field in COUNTS}

    if kind == DatasetKind.PUBLIC:
        if not 1 <= draft.candidate_number <= len(candidates):
            raise _Rejected("unknown_candidate")
        page = candidates[draft.candidate_number - 1]
        page_text = f"{page.title} {page.snippet}"
        return DatasetOption(
            kind=kind,
            name=name,
            source=page.publisher or "Unknown site",
            url=page.url,
            size=_supported(size, page_text, check_words=False),
            labels=NOT_STATED if _not_stated(labels) else labels,
            license=_supported(license_, page_text, check_words=True),
            relevance=relevance,
            fit=fit,
            how_to_get=None,
            **lists,
        )
    return DatasetOption(
        kind=kind,
        name=name,
        source=OWN_DATA_SOURCE,
        url=None,
        size=size,
        labels=labels,
        license=license_,
        relevance=relevance,
        fit=fit,
        how_to_get=how_to_get or None,
        **lists,
    )


def check_plan_draft(
    draft: LLMDatasetPlanDraft, input: FindDatasetsInput, candidates: list[DatasetCandidate]
) -> tuple[DatasetPlan | None, str | None]:
    """Turn a draft into a DatasetPlan, or return (None, the reason it was rejected)."""
    try:
        purpose = _clean(draft.purpose)
        if not purpose:
            raise _Rejected("empty")
        if len(purpose) > MAX_TEXT_CHARS:
            raise _Rejected("too_long")
        plan = DatasetPlan(
            purpose=purpose,
            primary=_option(draft.primary, candidates),
            alternative=_option(draft.alternative, candidates),
        )
    except _Rejected as rejected:
        return None, rejected.reason

    texts = [plan.purpose]
    for option in (plan.primary, plan.alternative):
        texts += [option.name, option.size, option.labels, option.license, option.relevance,
                  *option.main_features, *option.preprocessing, *option.limitations, option.how_to_get or ""]
    if any(contains_url(text) for text in texts):
        return None, "contains_url"

    broken = plan_rule_broken(
        plan,
        {c.url for c in candidates},
        preference=input.preference,
        previous=input.previous_plan,
    )
    if broken is not None:
        return None, broken
    return plan, None
