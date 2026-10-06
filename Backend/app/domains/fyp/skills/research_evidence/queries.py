"""
The research plan (Release 0.4): which searches to run, step by step.

Deterministic templates — no AI needed to decide what to search for.
The branch is put in quotes so search engines treat it as an exact phrase.

Steps, in the order the student sees them:

  1. Discovering startups          startup directories (YC, Product Hunt, …)      → Tier C leads
  2. Confirming on startup websites  second hop: each startup found in step 1 is
                                   searched by name; its own website is kept     → Tier A
  3. Reading industry news         news search                                    → Tier B / C
  4. Reviewing government evidence government initiatives, programmes, reports  → Tier A
  5. Checking research papers      Google Scholar (or paper sites)                → Tier A / B
  6. Finding public datasets       official data portals and dataset platforms    → Tier A / B

Step 2's searches can't be written in advance — they are built from what step 1
finds (see startups.py). Every other step's searches are listed here.

The labels are the safe activity messages the student sees while Grey works.
"""
from dataclasses import dataclass, field

from app.core.brain.schemas import ResearchCategory
from app.core.tools.search import SearchFocus, SearchQuery
from app.domains.fyp.skills.research_evidence.sources import (
    COMMUNITY_DATASET_SITES,
    GOVERNMENT_SEARCH_SITES,
    OFFICIAL_DATA_PORTALS,
    PEER_REVIEWED_PUBLISHERS,
    PREPRINT_SERVERS,
    STARTUP_PROFILE_SITES,
)

# Step ids (also used as the checklist ids in research events).
DISCOVER_STARTUPS = "discover_startups"
CONFIRM_STARTUPS = "confirm_startups"
INDUSTRY_NEWS = "industry_news"
GOVERNMENT = "government"
RESEARCH_PAPERS = "research_papers"
DATASETS = "datasets"

EVALUATING_LABEL = "Evaluating evidence quality"

# Results asked for per search. More than the few kept per step, so the
# filters have choices — a search costs the same credit for 5 or 20 results.
RESULTS_PER_SEARCH = 10
# Startup discovery needs many profile pages to read names from (directory
# searches also return category pages like "Healthcare Startups funded by YC").
DISCOVERY_RESULTS = 20

# Most startups confirmed on their own website per research run.
MAX_STARTUPS_TO_CONFIRM = 5
# Results asked for when confirming one startup (its site is usually first).
CONFIRM_RESULTS_PER_STARTUP = 3


@dataclass(frozen=True)
class ResearchStep:
    id: str
    category: ResearchCategory       # saved with each source found in this step
    label: str                       # shown to the student while this step runs
    queries: list[SearchQuery] = field(default_factory=list)


# (step id, category, student-facing label, [(query template, focus, sites to search), …])
_PLAN = [
    (DISCOVER_STARTUPS, ResearchCategory.ORGANIZATIONS, "Discovering startups", [
        ('"{branch}" {industry} startups', SearchFocus.COMPANIES, STARTUP_PROFILE_SITES),
    ]),
    (CONFIRM_STARTUPS, ResearchCategory.ORGANIZATIONS, "Confirming on startup websites", []),
    (INDUSTRY_NEWS, ResearchCategory.NEWS, "Reading industry news", [
        ('"{branch}" {industry} technology', SearchFocus.NEWS, []),
    ]),
    (GOVERNMENT, ResearchCategory.OFFICIAL_SOURCES, "Reviewing government evidence", [
        ('"{branch}" {industry} government initiative programme', SearchFocus.GOVERNMENT, GOVERNMENT_SEARCH_SITES),
        ('"{branch}" {industry} government report strategy', SearchFocus.GOVERNMENT, GOVERNMENT_SEARCH_SITES),
    ]),
    (RESEARCH_PAPERS, ResearchCategory.RESEARCH, "Checking research papers", [
        # Google Scholar answers this directly; the site list helps providers without Scholar.
        ('"{branch}" {industry} machine learning', SearchFocus.RESEARCH,
         PEER_REVIEWED_PUBLISHERS + PREPRINT_SERVERS),
    ]),
    (DATASETS, ResearchCategory.DATASETS, "Finding public datasets", [
        ('"{branch}" {industry} dataset', SearchFocus.DATASETS, OFFICIAL_DATA_PORTALS + COMMUNITY_DATASET_SITES),
    ]),
]

# The student-facing label for each step, in research order.
STEP_LABELS: dict[str, str] = {step_id: label for step_id, _, label, _ in _PLAN}


def build_research_plan(industry: str, branch: str) -> list[ResearchStep]:
    """Return the research steps in order. The confirm step starts empty (filled from step 1)."""
    return [
        ResearchStep(
            id=step_id,
            category=category,
            label=label,
            queries=[
                SearchQuery(
                    text=template.format(industry=industry, branch=branch),
                    focus=focus,
                    max_results=DISCOVERY_RESULTS if step_id == DISCOVER_STARTUPS else RESULTS_PER_SEARCH,
                    include_domains=list(sites),
                )
                for template, focus, sites in templates
            ],
        )
        for step_id, category, label, templates in _PLAN
    ]


def confirm_query(startup_name: str, branch: str) -> SearchQuery:
    """The second-hop search for one startup: its name as an exact phrase, plus the branch."""
    return SearchQuery(
        text=f'"{startup_name}" {branch}',
        focus=SearchFocus.COMPANIES,
        max_results=CONFIRM_RESULTS_PER_STARTUP,
    )
