"""
Model search for the find_models skill (Release 0.9) — plain code, no AI.

Builds a few targeted searches from the student's approved project and keeps
only pages about ONE model, API or code base:

  1. "<branch> <task> pretrained model"  on Hugging Face and Kaggle models
  2. "<problem title> model code"        on GitHub and Papers with Code
  3. "<task> pretrained model pytorch"   on PyTorch Hub, Hugging Face and Kaggle
  4. "<task> API service"                on cloud AI service pages

A re-search for "other models" uses different wording and skips every page
shown before. The runner (search loop, budget, duplicates, failures) is the
one the dataset search uses (find_datasets/search.py), with a model-page filter.
"""
import re
from urllib.parse import urlparse

from app.core.brain.schemas import ModelPreference
from app.core.tools.search import SearchFocus, SearchQuery
from app.domains.fyp.skills.find_datasets.search import _GENERIC_WORDS, _readable, _short_title
from app.domains.fyp.skills.research_evidence.sources import host_in

MODEL_HUB_SITES = ["huggingface.co", "kaggle.com"]
CODE_SITES = ["github.com", "paperswithcode.com"]
FRAMEWORK_SITES = ["pytorch.org", "huggingface.co", "kaggle.com"]
CLOUD_AI_SITES = ["cloud.google.com", "aws.amazon.com", "learn.microsoft.com", "azure.microsoft.com"]
ALL_MODEL_SITES = [*MODEL_HUB_SITES, *CODE_SITES, "pytorch.org", *CLOUD_AI_SITES]

RESULTS_PER_SEARCH = 5

# Hugging Face paths that are not a model page.
_HF_NOT_MODELS = {
    "datasets", "spaces", "docs", "blog", "papers", "tasks", "learn", "models", "organizations",
    "pricing", "login", "join", "collections", "posts", "settings", "enterprise", "search",
}
_GITHUB_NOT_REPOS = {
    "topics", "search", "orgs", "features", "marketplace", "collections",
    "trending", "about", "login", "join", "explore", "sponsors", "settings",
}
_MODEL_PATHS = {
    "kaggle.com": re.compile(r"^/models/[^/]+/[^/]+"),
    "pytorch.org": re.compile(r"^/hub/[^/]+"),
    "paperswithcode.com": re.compile(r"^/(paper|method)/[^/]+"),
}


def _query(text: str, sites: list[str]) -> SearchQuery:
    # General focus: a "research" focus would send SerpAPI to Google Scholar, which ignores the sites.
    return SearchQuery(
        text=" ".join(text.split()),
        focus=SearchFocus.GENERAL,
        max_results=RESULTS_PER_SEARCH,
        include_domains=sites,
    )


def build_model_queries(
    industry: str,
    branch: str,
    problem_title: str,
    task: str,
    preference: ModelPreference | None = None,
) -> list[SearchQuery]:
    """The searches for one model run. `task` is the AI task type, e.g. "anomaly_detection"."""
    task = _readable(task)
    title = _short_title(problem_title)
    if preference == ModelPreference.OTHER_OPTIONS:
        return [
            _query(f"{industry} {task} model", ["huggingface.co"]),
            _query(f"{task} {branch} open source implementation", ["github.com"]),
            _query(f"{title} API", CLOUD_AI_SITES),
        ]
    return [
        _query(f"{branch} {task} pretrained model", MODEL_HUB_SITES),
        _query(f"{title} model code", CODE_SITES),
        _query(f"{task or branch} pretrained model pytorch", FRAMEWORK_SITES),
        _query(f"{task or branch} API service", CLOUD_AI_SITES),
    ]


def is_model_page(url: str) -> bool:
    """True if the page looks like it is about ONE model, API or code base (not a hub's home or search page)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    if host_in(host, ["huggingface.co"]):
        return len(parts) >= 2 and parts[0].lower() not in _HF_NOT_MODELS
    if host_in(host, ["github.com"]):
        return len(parts) >= 2 and parts[0].lower() not in _GITHUB_NOT_REPOS
    for site, pattern in _MODEL_PATHS.items():
        if host_in(host, [site]):
            return bool(pattern.search(path))
    if host_in(host, CLOUD_AI_SITES):
        return len(parts) >= 2 and parts[-1].lower() not in _GENERIC_WORDS
    return bool(parts) and parts[-1].lower() not in _GENERIC_WORDS
