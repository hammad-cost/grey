"""
Tests for evidence classification: source type, tier, and the text fields.
"""
import pytest

from app.core.brain.schemas import EvidenceTier, ResearchCategory, SourceType
from app.core.tools.search import SearchResult
from app.domains.fyp.skills.research_evidence.classification import (
    classify,
    organization_name,
    split_snippet,
    why_it_matters,
)

A, B, C = EvidenceTier.A, EvidenceTier.B, EvidenceTier.C
ORG = ResearchCategory.ORGANIZATIONS
OFFICIAL = ResearchCategory.OFFICIAL_SOURCES
RESEARCH = ResearchCategory.RESEARCH
DATA = ResearchCategory.DATASETS


def result(url: str, publisher: str | None = None, title: str = "Some page") -> SearchResult:
    return SearchResult(title=title, url=url, snippet="Problem. Insight.", publisher=publisher)


@pytest.mark.parametrize("url, publisher, title, category, expected_type, expected_tier", [
    # ── Tier A: government ──
    ("https://www.navy.mil/initiatives/x", None, "Fleet modernisation", OFFICIAL, SourceType.GOVERNMENT_INITIATIVE, A),
    ("https://www.gov.uk/government/publications/x", None, "Annual review", OFFICIAL, SourceType.GOVERNMENT_REPORT, A),
    ("https://agency.gov/programs/x", None, "Pilot program", OFFICIAL, SourceType.OFFICIAL_PROGRAM, A),
    ("https://challenges.gov.example/x", None, "Open innovation challenge", OFFICIAL, SourceType.PUBLIC_CHALLENGE, A),
    ("https://data.gov/dataset/x", None, "Vessel records", DATA, SourceType.DATASET, A),
    ("https://www.finance.gov.pk/x", None, "Digital banking", OFFICIAL, SourceType.GOVERNMENT_INITIATIVE, A),
    # ── Tier A: peer-reviewed research ──
    ("https://doi.org/10.1000/xyz", None, "A study", RESEARCH, SourceType.RESEARCH_PAPER, A),
    ("https://journals.research.example/a", "Journal of X (peer-reviewed)", "Review", RESEARCH, SourceType.RESEARCH_PAPER, A),
    # ── Tier A: official organization websites ──
    ("https://www.northwind.example/solutions", "Northwind (sample startup)", "Platform", ORG, SourceType.STARTUP, A),
    ("https://www.meridian.example/products", "Meridian Systems", "Platform", ORG, SourceType.COMPANY, A),
    # ── Tier B ──
    ("https://arxiv.org/abs/2401.00001", None, "Preprint", RESEARCH, SourceType.RESEARCH_PAPER, B),
    ("https://www.cs.mit.edu/research/x", None, "Lab news", RESEARCH, SourceType.UNIVERSITY_RESEARCH, B),
    ("https://www.imperial.ac.uk/news/x", None, "Announcement", RESEARCH, SourceType.UNIVERSITY_RESEARCH, B),
    ("https://www.reuters.com/technology/x", None, "Industry story", ORG, SourceType.NEWS, B),
    ("https://www.tech-times.example/news/x", "Tech Times (sample news site)", "Story", ORG, SourceType.NEWS, B),
    ("https://www.kaggle.com/datasets/x", None, "Data", DATA, SourceType.DATASET, B),
    ("https://github.com/org/project", None, "Tool", ORG, SourceType.OPEN_SOURCE, B),
    # ── Tier C: discovery only ──
    ("https://startups.directory.example/x", "Startup Directory", "Top startups", ORG, SourceType.STARTUP, C),
    ("https://www.crunchbase.com/organization/x", None, "Profile", ORG, SourceType.STARTUP, C),
    ("https://blog.industry-insights.example/posts/x", None, "Trends", ORG, SourceType.OTHER, C),
    ("https://medium.com/@someone/x", None, "My thoughts", RESEARCH, SourceType.OTHER, C),
    ("https://www.reddit.com/r/x", None, "Discussion", RESEARCH, SourceType.OTHER, C),
    ("https://unknown-site.example/x", None, "Something", RESEARCH, SourceType.OTHER, C),
])
def test_classify(url, publisher, title, category, expected_type, expected_tier):
    assert classify(result(url, publisher, title), category) == (expected_type, expected_tier)


def test_title_words_do_not_change_the_kind_of_site():
    """A headline mentioning 'accelerator' or 'times' doesn't make a company page a directory or news."""
    page = result("https://www.meridian.example/p", "Meridian Systems", "Meridian GPU accelerator saves time, sometimes")
    assert classify(page, ORG) == (SourceType.COMPANY, A)


def test_lookalike_government_hosts_are_not_government():
    """'governance' or 'gov' inside a word is not a government site."""
    page = result("https://governance-weekly.example/x", None, "Policy piece")
    assert classify(page, RESEARCH) == (SourceType.OTHER, C)


def test_preprints_are_never_tier_a_even_on_journal_like_sites():
    page = result("https://preprints.journal-archive.example/x", "Preprint server", "Paper")
    assert classify(page, RESEARCH) == (SourceType.RESEARCH_PAPER, B)


# ── Text fields ───────────────────────────────────────────────────────────────

def test_split_snippet_two_sentences():
    problem, insight = split_snippet("Ports are congested. A model cut waiting times by 12%.")
    assert problem == "Ports are congested."
    assert insight == "A model cut waiting times by 12%."


def test_split_snippet_several_sentences_keeps_rest_as_insight():
    problem, insight = split_snippet("Problem here! First detail. Second detail?")
    assert problem == "Problem here!"
    assert insight == "First detail. Second detail?"


def test_split_snippet_one_sentence_used_for_both():
    assert split_snippet("  Only one sentence  ") == ("Only one sentence", "Only one sentence")


def test_organization_name_prefers_publisher():
    assert organization_name(result("https://www.x.example/a", "  Example Agency ")) == "Example Agency"


def test_organization_name_falls_back_to_host():
    assert organization_name(result("https://www.x.example/a", None)) == "x.example"
    assert organization_name(result("https://www.x.example/a", "   ")) == "x.example"


def test_why_it_matters_names_tier_type_and_branch():
    text = why_it_matters(A, SourceType.OFFICIAL_PROGRAM, "Defense", "Navy")
    assert text == "Strong evidence (Tier A): an official, funded programme targeting this problem in Navy (Defense)."


def test_why_it_matters_warns_about_tier_c():
    assert "confirm with stronger sources" in why_it_matters(C, SourceType.OTHER, "Finance", "Banking")


@pytest.mark.parametrize("source_type", list(SourceType))
@pytest.mark.parametrize("tier", list(EvidenceTier))
def test_why_it_matters_covers_every_type_and_tier(source_type, tier):
    assert why_it_matters(tier, source_type, "Finance", "Banking")


# ── Real-world sites (Release 0.4) ────────────────────────────────────────────

from app.domains.fyp.skills.research_evidence.classification import clean_snippet  # noqa: E402
from app.domains.fyp.skills.research_evidence.sources import host_in  # noqa: E402


@pytest.mark.parametrize("url, publisher, title, category, expected_type, expected_tier", [
    # Startup directories → discovery only
    ("https://www.ycombinator.com/companies/harbor-ai", "Y Combinator", "Harbor AI", ORG, SourceType.STARTUP, C),
    ("https://www.producthunt.com/products/x", None, "X", ORG, SourceType.STARTUP, C),
    ("https://app.dealroom.co/companies/x", None, "X", ORG, SourceType.STARTUP, C),
    ("https://www.f6s.com/company/x", None, "X", ORG, SourceType.STARTUP, C),
    # News: listed outlets B; the news site wins over the word "journal"
    ("https://www.wsj.com/tech/x", "The Wall Street Journal", "AI at sea", ORG, SourceType.NEWS, B),
    ("https://techcrunch.com/2026/03/01/x", "TechCrunch", "Startup raises", ORG, SourceType.NEWS, B),
    ("https://www.bbc.co.uk/news/x", None, "Story", ORG, SourceType.NEWS, B),
    # Research: publishers A, preprints B
    ("https://ieeexplore.ieee.org/document/1", "J Smith - IEEE Access, 2024 - ieeexplore.ieee.org", "Paper", RESEARCH, SourceType.RESEARCH_PAPER, A),
    ("https://link.springer.com/article/x", None, "Paper", RESEARCH, SourceType.RESEARCH_PAPER, A),
    ("https://www.mdpi.com/2077-1312/1/1", None, "Paper", RESEARCH, SourceType.RESEARCH_PAPER, A),
    ("https://www.researchgate.net/publication/x", None, "Paper", RESEARCH, SourceType.RESEARCH_PAPER, B),
    ("https://openreview.net/forum?id=x", None, "Paper", RESEARCH, SourceType.RESEARCH_PAPER, B),
    # Government and international bodies (worldwide)
    ("https://www.gov.pk/x", None, "Policy", OFFICIAL, SourceType.GOVERNMENT_INITIATIVE, A),
    ("https://www.canada.ca.gc.ca/x", None, "Plan", OFFICIAL, SourceType.GOVERNMENT_INITIATIVE, A),
    ("https://www.economie.gouv.fr/x", None, "Plan", OFFICIAL, SourceType.GOVERNMENT_INITIATIVE, A),
    ("https://digital-strategy.ec.europa.eu/x", None, "AI programme", OFFICIAL, SourceType.OFFICIAL_PROGRAM, A),
    ("https://www.nato.int/cps/x", None, "Annual report", OFFICIAL, SourceType.GOVERNMENT_REPORT, A),
    # Datasets
    ("https://catalog.data.gov/dataset/ais", None, "AIS data", DATA, SourceType.DATASET, A),
    ("https://zenodo.org/records/1", None, "Dataset", DATA, SourceType.DATASET, A),
    ("https://huggingface.co/datasets/x", None, "Data", DATA, SourceType.DATASET, B),
    # Social / blogs → discovery only
    ("https://www.linkedin.com/pulse/x", None, "Thoughts", ORG, SourceType.OTHER, C),
    ("https://someone.substack.com/p/x", None, "Essay", ORG, SourceType.OTHER, C),
    # A startup's own site (second search hop) → primary evidence
    ("https://harbor-ai.com/", "Harbor AI", "Harbor AI — vessel monitoring", ORG, SourceType.COMPANY, A),
])
def test_classify_real_sites(url, publisher, title, category, expected_type, expected_tier):
    assert classify(result(url, publisher, title), category) == (expected_type, expected_tier)


def test_headline_words_never_make_a_paper():
    """'journal' or 'preprint' in a headline on an unknown site isn't research."""
    page = result("https://some-company.com/news", "Some Company", "Our journal of a new preprint", )
    assert classify(page, RESEARCH) == (SourceType.OTHER, C)


def test_host_in_covers_subdomains_but_not_lookalikes():
    assert host_in("link.springer.com", ["springer.com"])
    assert host_in("www.reuters.com", ["reuters.com"])
    assert not host_in("notreuters.com", ["reuters.com"])
    assert not host_in("reuters.com.evil.example", ["reuters.com"])


@pytest.mark.parametrize("publisher, url, expected", [
    ("J Smith, A Lee - IEEE Access, 2024 - ieeexplore.ieee.org", "https://ieeexplore.ieee.org/x", "IEEE Access"),
    ("Reuters", "https://www.reuters.com/x", "Reuters"),
    ("www.navy.mil › programme", "https://www.navy.mil/programme", "navy.mil"),
    ("harbor-ai.com", "https://harbor-ai.com/", "harbor-ai.com"),
    (None, "https://www.zenodo.org/records/1", "zenodo.org"),
])
def test_organization_name_for_real_results(publisher, url, expected):
    assert organization_name(result(url, publisher)) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Mar 3, 2026 — The navy funds <b>maritime</b> autonomy.", "The navy funds maritime autonomy."),
    ("3 days ago ... Startups &amp; agencies test AIS models.", "Startups & agencies test AIS models."),
    ("12 March 2026 · Ports face congestion.", "Ports face congestion."),
    ("No date here, just text.", "No date here, just text."),
])
def test_clean_snippet(raw, expected):
    assert clean_snippet(raw) == expected


def test_split_snippet_cleans_real_snippets_first():
    problem, insight = split_snippet("Mar 3, 2026 — Ports face <i>congestion</i>. AI scheduling cut delays by 20%.")
    assert problem == "Ports face congestion."
    assert insight == "AI scheduling cut delays by 20%."
