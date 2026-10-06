"""
Checks every FYP design the model returns. Plain code — no AI.

A draft becomes an FYPDesign only if it passes every check; otherwise the
first failing rule is returned and the skill asks once more.

  contains_url               — a link appears anywhere (links only come from the database)
  too_long                   — a field is far longer than asked for
  names_organization         — an evidence organization is named in the title, summary
                               or contribution ("copy this company's product")
  names_specific_technology  — a named dataset, model, library, API, cloud service…
                               (Release 0.5 designs WHAT is built; HOW comes later)
  unchanged                  — a redesign kept the same title and summary
"""
from app.core.brain.schemas import FYPDesign
from app.domains.fyp.skills.design_fyp.schemas import DesignFYPInput, LLMFYPDesignDraft
from app.domains.fyp.skills.fyp_design_shared import contains_url, named_technology, names_organization

MAX_TITLE_CHARS = 120
MAX_TEXT_CHARS = 500

_FIELDS = ("title", "summary", "target_user", "system_input", "system_output",
           "main_contribution", "scope_reduction")
_NAMING_FIELDS = ("title", "summary", "main_contribution")


def _same(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def check_design(draft: LLMFYPDesignDraft, input: DesignFYPInput) -> tuple[FYPDesign | None, str | None]:
    """Turn a draft into an FYPDesign, or return (None, the reason it was rejected)."""
    texts = {field: " ".join(getattr(draft, field).split()) for field in _FIELDS}

    if any(not text for text in texts.values()):
        return None, "empty"
    if any(contains_url(text) for text in texts.values()):
        return None, "contains_url"
    if len(texts["title"]) > MAX_TITLE_CHARS or any(len(t) > MAX_TEXT_CHARS for t in texts.values()):
        return None, "too_long"
    if any(names_organization(texts[f], input.problem.organizations) for f in _NAMING_FIELDS):
        return None, "names_organization"
    if any(named_technology(text) for text in texts.values()):
        return None, "names_specific_technology"
    previous = input.previous_design
    if previous is not None and _same(texts["title"], previous.title) and _same(texts["summary"], previous.summary):
        return None, "unchanged"
    return FYPDesign(**texts), None
