"""
Dataset search for the find_datasets skill (Release 0.8) — plain code, no AI.

Builds a few targeted searches from the student's approved project, runs them
through the SearchProvider (usually the SearchGateway) and keeps only pages
that are really about one dataset:

  1. "<branch> <task> dataset"           on Kaggle and Hugging Face
  2. "<problem title> dataset"           on Kaggle, Hugging Face, UCI and Zenodo
  3. "<branch> <industry> open data"     on official open-data portals
  4. "<task> <branch> benchmark dataset" on Papers with Code and GitHub

A re-search for "other options" uses different wording and skips every page
shown before. "I'd rather create or collect my own data" makes no new searches.

Generic pages (a portal's home, about, search or metrics page — the kind the
0.4 live run returned) are dropped: on the big dataset sites a page must have
the site's dataset path (e.g. kaggle.com/datasets/<owner>/<name>).
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.core.brain.schemas import DatasetCandidate, DatasetPreference
from app.core.tools.search import SearchFocus, SearchProvider, SearchProviderError, SearchQuery, SearchResult
from app.domains.fyp.skills.research_evidence.classification import clean_snippet
from app.domains.fyp.skills.research_evidence.sources import (
    COMMUNITY_DATASET_SITES,
    OFFICIAL_DATA_PORTALS,
    host_in,
)

# Where the searches look.
COMMUNITY_SITES = ["kaggle.com", "huggingface.co"]
REPOSITORY_SITES = ["kaggle.com", "huggingface.co", "archive.ics.uci.edu", "zenodo.org"]
PORTAL_SITES = [site for site in OFFICIAL_DATA_PORTALS if site not in ("zenodo.org", "archive.ics.uci.edu")]
BENCHMARK_SITES = ["paperswithcode.com", "github.com"]
ALL_DATASET_SITES = [*OFFICIAL_DATA_PORTALS, *COMMUNITY_DATASET_SITES, "github.com"]

RESULTS_PER_SEARCH = 5
MAX_CANDIDATES = 8           # pages the model chooses from (keeps the prompt small)
MAX_SNIPPET_CHARS = 300
MAX_TITLE_WORDS = 8          # long problem titles make poor searches

# On these sites a dataset page has a known path; anything else there is a generic page.
_DATASET_PATHS = {
    "kaggle.com": re.compile(r"^/datasets/[^/]+/[^/]+"),
    "huggingface.co": re.compile(r"^/datasets/[^/]+"),
    "archive.ics.uci.edu": re.compile(r"^/(dataset/\d+|ml/datasets/[^/]+)"),
    "zenodo.org": re.compile(r"^/records?/\d+"),
    "paperswithcode.com": re.compile(r"^/dataset/[^/]+"),
    "catalog.data.gov": re.compile(r"^/dataset/[^/]+"),
    "data.gov.uk": re.compile(r"^/dataset/[^/]+"),
    "data.europa.eu": re.compile(r"/datasets?/[^/]+"),
    "data.worldbank.org": re.compile(r"^/(indicator|dataset)/[^/]+"),
    "datacatalog.worldbank.org": re.compile(r"/dataset/[^/]+"),
}
# Hosts that are only ever portal front pages (their datasets live on another host).
_FRONT_PAGE_HOSTS = {"data.gov"}
# GitHub paths that are not repositories.
_GITHUB_NOT_REPOS = {
    "topics", "search", "orgs", "features", "marketplace", "collections",
    "trending", "about", "login", "join", "explore", "sponsors", "settings",
}
# Last path words that mean "a list, a menu or an info page", not one dataset.
_GENERIC_WORDS = {
    "", "about", "search", "metrics", "login", "signin", "signup", "register", "home", "index",
    "help", "faq", "contact", "terms", "privacy", "blog", "news", "tags", "topics", "categories",
    "datasets", "data", "explore", "browse", "catalog", "catalogue", "user-guide", "docs",
}


@dataclass
class DatasetSearchResult:
    """What the dataset search found."""
    candidates: list[DatasetCandidate] = field(default_factory=list)
    searches_used: int = 0
    searches_failed: int = 0


def _readable(value: str) -> str:
    """'anomaly_detection' → 'anomaly detection'; 'other' / 'none' → ''."""
    return "" if value in ("", "other", "none") else value.replace("_", " ")


def _short_title(title: str) -> str:
    words = re.sub(r"[^\w\s-]", " ", title).split()
    return " ".join(words[:MAX_TITLE_WORDS])


def _query(text: str, sites: list[str]) -> SearchQuery:
    return SearchQuery(
        text=" ".join(text.split()),
        focus=SearchFocus.DATASETS,
        max_results=RESULTS_PER_SEARCH,
        include_domains=sites,
    )


def build_dataset_queries(
    industry: str,
    branch: str,
    problem_title: str,
    task: str,
    preference: DatasetPreference | None = None,
) -> list[SearchQuery]:
    """
    The searches for one dataset run. `task` is the AI task type (or the problem's
    task type when the project doesn't use AI), e.g. "anomaly_detection".
    """
    task = _readable(task)
    title = _short_title(problem_title)
    if preference == DatasetPreference.OWN_DATA:
        return []
    if preference == DatasetPreference.OTHER_OPTIONS:
        return [
            _query(f"{industry} {task} labelled dataset", COMMUNITY_SITES),
            _query(f"{title} data", ["zenodo.org", "archive.ics.uci.edu", "github.com"]),
            _query(f"{branch} public dataset", ALL_DATASET_SITES),
        ]
    return [
        _query(f"{branch} {task} dataset", COMMUNITY_SITES),
        _query(f"{title} dataset", REPOSITORY_SITES),
        _query(f"{branch} {industry} open data", PORTAL_SITES),
        _query(f"{task or branch} {branch if task else ''} benchmark dataset", BENCHMARK_SITES),
    ]


def normalize_url(url: str) -> str:
    """Drop the #fragment and a trailing slash, so the same page isn't kept twice."""
    return url.split("#", 1)[0].rstrip("/")


def is_dataset_page(url: str) -> bool:
    """True if the page looks like it is about ONE dataset (not a portal's home, search or about page)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")

    if host in _FRONT_PAGE_HOSTS:
        return False
    for site, pattern in _DATASET_PATHS.items():
        if host_in(host, [site]):
            return bool(pattern.search(path))
    if host_in(host, ["github.com"]):
        parts = [p for p in path.split("/") if p]
        return len(parts) >= 2 and parts[0].lower() not in _GITHUB_NOT_REPOS
    last = path.split("/")[-1].lower() if path else ""
    return last not in _GENERIC_WORDS


def _candidate(result: SearchResult, query: SearchQuery, provider: str) -> DatasetCandidate:
    snippet = clean_snippet(result.snippet) or result.title
    if len(snippet) > MAX_SNIPPET_CHARS:
        snippet = snippet[: MAX_SNIPPET_CHARS - 1].rstrip() + "…"
    host = (urlparse(result.url).hostname or "").removeprefix("www.")
    return DatasetCandidate(
        title=result.title.strip(),
        url=normalize_url(result.url),
        snippet=snippet,
        publisher=result.publisher or host or None,
        query=query.text,
        provider=result.provider or provider,
    )


async def search_datasets(
    search: SearchProvider,
    queries: list[SearchQuery],
    *,
    max_searches: int,
    known: list[DatasetCandidate] | None = None,
    exclude_urls: set[str] | None = None,
    on_search=None,
) -> DatasetSearchResult:
    """
    Run the searches and return the dataset pages found, best (earliest) first.

    `known` are pages earlier runs found (offered again if not excluded);
    `exclude_urls` are pages already shown to the student.
    A failed search is skipped; if EVERY search fails and nothing is known,
    the last SearchProviderError is raised, so the caller can say "try again".
    `on_search(index, total)` is awaited before each search (for progress).
    """
    exclude = {normalize_url(u) for u in exclude_urls or set()}
    found = DatasetSearchResult()
    seen: set[str] = set(exclude)

    def keep(candidate: DatasetCandidate) -> None:
        if candidate.url not in seen and len(found.candidates) < MAX_CANDIDATES:
            seen.add(candidate.url)
            found.candidates.append(candidate)

    last_error: SearchProviderError | None = None
    planned = queries[:max_searches]
    for index, query in enumerate(planned):
        if on_search is not None:
            await on_search(index, len(planned))
        found.searches_used += 1
        try:
            results = await search.search(query)
        except SearchProviderError as error:
            found.searches_failed += 1
            last_error = error
            continue
        for result in results:
            if is_dataset_page(result.url):
                keep(_candidate(result, query, search.name))

    for candidate in known or []:
        keep(candidate)

    if planned and found.searches_failed == len(planned) and not found.candidates and last_error is not None:
        raise last_error
    return found
