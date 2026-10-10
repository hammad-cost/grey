"""
Model rules (Release 0.9) — plain code, no AI.

One place decides whether a model plan is honest and whether a re-search the
student asks for makes sense, so the skill, the workflow and the Project Brain
always apply the same rules:

  - a project without AI lists no models
  - every option links to a page the search really found (never an invented one)
  - no page is listed twice
  - "Look for other models" never shows a page shown before
"""
from app.core.brain.schemas import ModelPlan, ModelPreference


class ModelRuleError(ValueError):
    """The plan, or the re-search the student asked for, breaks a rule."""


def plan_rule_broken(
    plan: ModelPlan,
    found_urls: set[str],
    *,
    preference: ModelPreference | None = None,
    previous: ModelPlan | None = None,
) -> str | None:
    """The first rule the plan breaks (a short code), or None if it is fine."""
    if not plan.needs_model:
        return "options_without_ai" if plan.options else None
    urls = [option.url for option in plan.options]
    if any(url not in found_urls for url in urls):
        return "link_not_found_by_search"
    if len(set(urls)) != len(urls):
        return "same_model"
    if preference == ModelPreference.OTHER_OPTIONS and previous is not None:
        shown = {option.url for option in previous.options}
        if shown & set(urls):
            return "repeated_model"
    return None


def check_plan(
    plan: ModelPlan,
    found_urls: set[str],
    *,
    preference: ModelPreference | None = None,
    previous: ModelPlan | None = None,
) -> None:
    """Raise ModelRuleError if the plan breaks a rule."""
    broken = plan_rule_broken(plan, found_urls, preference=preference, previous=previous)
    if broken is not None:
        raise ModelRuleError(f"The model plan breaks a rule ({broken}).")


def research_problem(plan: ModelPlan, preference: ModelPreference) -> str | None:
    """Why this re-search makes no sense for the current plan (a message), or None if it is fine."""
    if not plan.needs_model:
        return "Your project doesn't use AI, so there are no models to look for."
    return None
