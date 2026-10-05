"""
The research plan: which searches to run for each research category.

Deterministic templates — no AI needed to decide what to search for.
The branch is put in quotes so search engines treat it as an exact phrase.

The labels are the safe activity messages the student sees while Grey works.
"""
from dataclasses import dataclass

from app.core.brain.schemas import ResearchCategory
from app.core.tools.search import SearchFocus, SearchQuery


@dataclass(frozen=True)
class CategoryPlan:
    category: ResearchCategory
    label: str                       # shown to the student while this category runs
    queries: list[SearchQuery]


# (category, student-facing label, [(query template, search focus), …])
_PLAN = [
    (
        ResearchCategory.ORGANIZATIONS,
        "Identifying relevant organizations",
        [
            ('"{branch}" {industry} startups and companies', SearchFocus.COMPANIES),
            ('"{branch}" {industry} industry news', SearchFocus.NEWS),
        ],
    ),
    (
        ResearchCategory.OFFICIAL_SOURCES,
        "Reviewing authoritative sources",
        [
            ('"{branch}" {industry} government initiatives and reports', SearchFocus.GOVERNMENT),
        ],
    ),
    (
        ResearchCategory.RESEARCH,
        "Checking research",
        [
            ('"{branch}" {industry} research papers', SearchFocus.RESEARCH),
        ],
    ),
    (
        ResearchCategory.DATASETS,
        "Checking datasets",
        [
            ('"{branch}" {industry} public datasets', SearchFocus.DATASETS),
        ],
    ),
]

EVALUATING_LABEL = "Evaluating evidence quality"

# The student-facing label for each category, in research order.
CATEGORY_LABELS: dict[ResearchCategory, str] = {category: label for category, label, _ in _PLAN}


def build_research_plan(industry: str, branch: str, max_results: int) -> list[CategoryPlan]:
    """Return the searches to run, category by category, in the order the student sees them."""
    return [
        CategoryPlan(
            category=category,
            label=label,
            queries=[
                SearchQuery(
                    text=template.format(industry=industry, branch=branch),
                    focus=focus,
                    max_results=max_results,
                )
                for template, focus in templates
            ],
        )
        for category, label, templates in _PLAN
    ]
