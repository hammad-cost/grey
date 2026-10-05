"""
Tests for the second search hop helpers (Release 0.4): reading startup names
from directory titles, and recognising a startup's own website.
"""
import pytest

from app.core.tools.search import SearchResult
from app.domains.fyp.skills.research_evidence.startups import (
    official_site,
    startup_name_from_title,
    startup_names,
)


def result(title: str, url: str = "https://www.ycombinator.com/companies/x") -> SearchResult:
    return SearchResult(title=title, url=url, snippet="Text.")


@pytest.mark.parametrize("title, expected", [
    ("Harbor AI: AI for ship monitoring | Y Combinator", "Harbor AI"),
    ("Harbor AI - Crunchbase Company Profile & Funding", "Harbor AI"),
    ("SeaSense | F6S", "SeaSense"),
    ("Orca Robotics – autonomous hull cleaning | Product Hunt", "Orca Robotics"),
    ("Top 10 maritime startups in 2026 | StartupBlink", None),
    ("Best Navy companies to watch", None),
    ("10 startups changing shipping", None),
    ("Case study: reducing errors in Navy workflows", None),
    ("Navy | Y Combinator", None),                      # just the branch name
    ("A very long title that is clearly not a company name at all", None),
])
def test_startup_name_from_title(title, expected):
    assert startup_name_from_title(title, "Defense", "Navy") == expected


def test_startup_names_are_distinct_ordered_and_limited():
    results = [result(t) for t in [
        "Harbor AI | Y Combinator", "harbor ai: profile | Crunchbase", "Top startups | List",
        "SeaSense | F6S", "Orca | Product Hunt", "Delta | Product Hunt",
    ]]
    assert startup_names(results, "Defense", "Navy", limit=3) == ["Harbor AI", "SeaSense", "Orca"]


@pytest.mark.parametrize("url, picked", [
    ("https://harbor-ai.com/", True),
    ("https://www.harborai.io/about", True),
    ("https://app.harbor.ai/", True),
    ("https://www.crunchbase.com/organization/harbor-ai", False),   # directory
    ("https://techcrunch.com/2026/harbor-ai-raises", False),        # news
    ("https://harbor-ai.substack.com/p/x", False),                  # blog platform
    ("https://harborai.gov/x", False),                              # government
    ("https://unrelated.com/harbor-ai", False),                     # name only in the path
])
def test_official_site(url, picked):
    found = official_site([SearchResult(title="Harbor AI", url=url, snippet="Text.")], "Harbor AI")
    assert (found is not None) == picked


def test_official_site_takes_the_first_good_result():
    results = [
        SearchResult(title="Profile", url="https://www.crunchbase.com/organization/harbor-ai", snippet="x"),
        SearchResult(title="Harbor AI", url="https://harbor-ai.com/", snippet="x"),
        SearchResult(title="Harbor AI docs", url="https://docs.harbor-ai.com/", snippet="x"),
    ]
    assert official_site(results, "Harbor AI").url == "https://harbor-ai.com/"
