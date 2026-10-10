"""
Dataset rules (Release 0.8) — plain code, no AI.

One place decides whether a dataset recommendation is honest and whether a
re-search the student asks for makes sense, so the skill, the workflow and the
Project Brain always apply the same rules:

  - a public dataset links to a page the search really found (never an invented one)
  - own data (synthetic or student-collected) has no link, but says how to get it
  - the primary and the alternative are different datasets
  - "I'd rather create or collect my own data" makes own data the primary choice
  - "Find other options" never recommends a public dataset shown before
"""
from app.core.brain.schemas import DatasetKind, DatasetOption, DatasetPlan, DatasetPreference

OWN_DATA_KINDS = {DatasetKind.SYNTHETIC, DatasetKind.STUDENT_COLLECTED}


class DatasetRuleError(ValueError):
    """The recommendation, or the re-search the student asked for, breaks a rule."""


def is_own_data(option: DatasetOption) -> bool:
    return option.kind in OWN_DATA_KINDS


def _option_rule_broken(option: DatasetOption, found_urls: set[str]) -> str | None:
    if is_own_data(option):
        if option.url is not None:
            return "link_for_own_data"
        if not option.how_to_get:
            return "missing_how_to_get"
        return None
    if option.url is None:
        return "missing_link"
    if option.url not in found_urls:
        return "link_not_found_by_search"
    return None


def _same_dataset(a: DatasetOption, b: DatasetOption) -> bool:
    if a.url is not None and a.url == b.url:
        return True
    return " ".join(a.name.lower().split()) == " ".join(b.name.lower().split())


def plan_rule_broken(
    plan: DatasetPlan,
    found_urls: set[str],
    *,
    preference: DatasetPreference | None = None,
    previous: DatasetPlan | None = None,
) -> str | None:
    """The first rule the recommendation breaks (a short code), or None if it is fine."""
    for option in (plan.primary, plan.alternative):
        broken = _option_rule_broken(option, found_urls)
        if broken is not None:
            return broken
    if _same_dataset(plan.primary, plan.alternative):
        return "same_dataset"
    if preference == DatasetPreference.OWN_DATA and not is_own_data(plan.primary):
        return "own_data_not_primary"
    if preference == DatasetPreference.OTHER_OPTIONS and previous is not None:
        shown = {o.url for o in (previous.primary, previous.alternative) if o.url}
        if any(o.url in shown for o in (plan.primary, plan.alternative) if o.url):
            return "repeated_dataset"
    return None


def check_plan(
    plan: DatasetPlan,
    found_urls: set[str],
    *,
    preference: DatasetPreference | None = None,
    previous: DatasetPlan | None = None,
) -> None:
    """Raise DatasetRuleError if the recommendation breaks a rule."""
    broken = plan_rule_broken(plan, found_urls, preference=preference, previous=previous)
    if broken is not None:
        raise DatasetRuleError(f"The dataset recommendation breaks a rule ({broken}).")


def research_problem(plan: DatasetPlan, preference: DatasetPreference) -> str | None:
    """Why this re-search makes no sense for the current recommendation (a message), or None if it is fine."""
    if preference == DatasetPreference.OWN_DATA and is_own_data(plan.primary):
        return "Your main dataset is already data you create or collect yourself."
    return None
