"""
Checks every project definition the model returns. Plain code — no AI.

A draft becomes a ProjectDefinition only if it passes every check; otherwise
the first failing rule is returned and the skill asks once more.

  empty                      — a text is empty
  wrong_count                — too few or too many modules, steps or features
  contains_url               — a link appears anywhere (links only come from the database)
  too_long                   — a title or text is far longer than asked for
  duplicate_feature          — two features share a title
  names_organization         — an evidence organization is named
  names_specific_technology  — a named dataset, model, library, API, cloud service…
                               (the technical plan comes in later stages)
"""
from app.core.brain.schemas import (
    ProblemDefinition,
    ProjectDefinition,
    ProposedSolution,
    ScopeItem,
    ScopeKind,
    SolutionModule,
)
from app.domains.fyp.skills.define_project.schemas import DefineProjectInput, LLMProjectDefinitionDraft
from app.domains.fyp.skills.fyp_design_shared import contains_url, named_technology, names_organization

MAX_TITLE_CHARS = 80
MAX_TEXT_CHARS = 500          # same limit as the FYP design texts

# (min, max) of each list Grey asks for.
COUNTS = {
    "modules": (2, 6),
    "workflow_steps": (3, 8),
    "core_features": (3, 6),
    "optional_features": (1, 4),
    "out_of_scope": (2, 5),
}

_FEATURE_LISTS = [
    ("core_features", ScopeKind.CORE),
    ("optional_features", ScopeKind.OPTIONAL),
    ("out_of_scope", ScopeKind.OUT_OF_SCOPE),
]


def _clean(text: str) -> str:
    return " ".join(text.split())


def check_definition(
    draft: LLMProjectDefinitionDraft, input: DefineProjectInput
) -> tuple[ProjectDefinition | None, str | None]:
    """Turn a draft into a ProjectDefinition, or return (None, the reason it was rejected)."""
    for field, (low, high) in COUNTS.items():
        if not low <= len(getattr(draft, field)) <= high:
            return None, "wrong_count"

    problem = {field: _clean(value) for field, value in draft.problem_definition.model_dump().items()}
    purpose = _clean(draft.system_purpose)
    modules = [(_clean(m.name), _clean(m.purpose)) for m in draft.modules]
    steps = [_clean(step) for step in draft.workflow_steps]
    features = [
        (_clean(f.title), _clean(f.description), kind)
        for field, kind in _FEATURE_LISTS
        for f in getattr(draft, field)
    ]

    titles = [name for name, _ in modules] + [title for title, _, _ in features]
    texts = (
        list(problem.values()) + [purpose] + steps
        + [p for _, p in modules] + [d for _, d, _ in features]
    )
    everything = titles + texts

    if any(not text for text in everything):
        return None, "empty"
    if any(contains_url(text) for text in everything):
        return None, "contains_url"
    if any(len(t) > MAX_TITLE_CHARS for t in titles) or any(len(t) > MAX_TEXT_CHARS for t in texts):
        return None, "too_long"
    feature_titles = [title.lower() for title, _, _ in features]
    if len(set(feature_titles)) != len(feature_titles):
        return None, "duplicate_feature"
    if any(names_organization(text, input.problem.organizations) for text in everything):
        return None, "names_organization"
    if any(named_technology(text) for text in everything):
        return None, "names_specific_technology"

    return ProjectDefinition(
        problem_definition=ProblemDefinition(**problem),
        proposed_solution=ProposedSolution(
            system_purpose=purpose,
            modules=[SolutionModule(name=name, purpose=p) for name, p in modules],
            workflow_steps=steps,
        ),
        scope=[ScopeItem(title=title, description=description, kind=kind) for title, description, kind in features],
    ), None
