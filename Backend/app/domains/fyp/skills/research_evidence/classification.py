"""
Turning a raw search result into Project Brain evidence — with simple rules, no AI.

1. classify()        → source type + evidence tier (product blueprint §11)
2. split_snippet()   → problem addressed + relevant insight
3. why_it_matters()  → a plain sentence explaining the source's value

Tier rules (first matching rule wins):

  Tier A — primary evidence
    government sites (.gov, .mil)        initiative / report / programme / challenge / dataset
    peer-reviewed research               journals, doi.org
    official company / startup websites  (organization search results)
  Tier B — strong secondary evidence
    university sites (.edu, .ac.)        university research
    preprints (arxiv, "preprint")        not yet peer-reviewed, so not Tier A
    reputable news / publications        news sites, known outlets
    community dataset platforms          kaggle, hugging face, dataset hubs
    open-source projects                 github, gitlab
  Tier C — discovery evidence
    directories, aggregators, accelerators, blogs, forums, anything unrecognised

Limitation: rules can't truly judge reputation. With the mock provider the
signals are reliable; a real provider will need these rules reviewed.
"""
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from app.core.brain.schemas import EvidenceTier, ResearchCategory, SourceType
from app.core.tools.search import SearchResult


@dataclass(frozen=True)
class _Page:
    """The parts of a search result the rules look at, lower-cased."""
    host: str
    path: str
    publisher: str
    title: str
    category: ResearchCategory

    def mentions(self, *words: str) -> bool:
        """Any of the words appears anywhere: host, path, publisher or title."""
        text = " ".join((self.host, self.path, self.publisher, self.title))
        return any(word in text for word in words)

    def site_is(self, *words: str) -> bool:
        """Any of the words appears in the host or publisher — i.e. describes the site itself,
        not just the page title (so a headline like "GPU accelerator" doesn't count)."""
        text = " ".join((self.host, self.publisher))
        return any(word in text for word in words)


def _is_government(page: _Page) -> bool:
    host = page.host
    return any(host.endswith(s) or f"{s}." in host for s in (".gov", ".mil")) or host.startswith("gov.")


def _is_university(page: _Page) -> bool:
    return any(page.host.endswith(s) or f"{s}." in page.host for s in (".edu", ".ac"))


_NEWS_HOSTS = ("reuters.", "bbc.", "apnews.", "ft.com", "bloomberg.", "techcrunch.", "wired.",
               "theverge.", "economist.", "nytimes.", "theguardian.", "dawn.com")

# (does this rule match?, source type, tier) — checked top to bottom, first match wins.
_RULES: list[tuple[Callable[[_Page], bool], SourceType, EvidenceTier]] = [
    # ── Government (Tier A) ───────────────────────────────────────────────────
    (lambda p: _is_government(p) and (p.category == ResearchCategory.DATASETS
                                      or p.mentions("data.", "dataset")),
     SourceType.DATASET, EvidenceTier.A),
    (lambda p: _is_government(p) and p.mentions("challenge"),
     SourceType.PUBLIC_CHALLENGE, EvidenceTier.A),
    (lambda p: _is_government(p) and p.mentions("report", "review", "audit"),
     SourceType.GOVERNMENT_REPORT, EvidenceTier.A),
    (lambda p: _is_government(p) and p.mentions("programme", "program"),
     SourceType.OFFICIAL_PROGRAM, EvidenceTier.A),
    (_is_government, SourceType.GOVERNMENT_INITIATIVE, EvidenceTier.A),

    # ── Research ──────────────────────────────────────────────────────────────
    (lambda p: p.mentions("arxiv", "preprint"), SourceType.RESEARCH_PAPER, EvidenceTier.B),
    (lambda p: p.mentions("doi.org", "journal", "peer-reviewed"),
     SourceType.RESEARCH_PAPER, EvidenceTier.A),
    (_is_university, SourceType.UNIVERSITY_RESEARCH, EvidenceTier.B),

    # ── Discovery-only sources (Tier C) — checked before company/news rules ──
    (lambda p: p.site_is("directory", "crunchbase", "aggregator", "accelerator"),
     SourceType.STARTUP, EvidenceTier.C),
    (lambda p: p.host.startswith("blog.") or "/blog" in p.path
     or p.site_is("blog", "medium.com", "reddit.", "forum", "substack."),
     SourceType.OTHER, EvidenceTier.C),

    # ── Datasets, open source, news (Tier B) ──────────────────────────────────
    (lambda p: p.category == ResearchCategory.DATASETS
     or p.mentions("kaggle.", "huggingface.", "dataset"),
     SourceType.DATASET, EvidenceTier.B),
    (lambda p: p.mentions("github.com", "gitlab.com"), SourceType.OPEN_SOURCE, EvidenceTier.B),
    (lambda p: any(h in p.host for h in _NEWS_HOSTS) or p.site_is("news", "times"),
     SourceType.NEWS, EvidenceTier.B),
    (lambda p: p.mentions("industry report", "market report", "whitepaper"),
     SourceType.INDUSTRY_REPORT, EvidenceTier.B),

    # ── Official organization websites (Tier A) ───────────────────────────────
    (lambda p: p.category == ResearchCategory.ORGANIZATIONS and p.mentions("startup"),
     SourceType.STARTUP, EvidenceTier.A),
    (lambda p: p.category == ResearchCategory.ORGANIZATIONS, SourceType.COMPANY, EvidenceTier.A),
]


def classify(result: SearchResult, category: ResearchCategory) -> tuple[SourceType, EvidenceTier]:
    """Decide what kind of source a result is and how strong it is as evidence."""
    url = urlparse(result.url)
    page = _Page(
        host=(url.hostname or "").lower(),
        path=url.path.lower(),
        publisher=(result.publisher or "").lower(),
        title=result.title.lower(),
        category=category,
    )
    for matches, source_type, tier in _RULES:
        if matches(page):
            return source_type, tier
    return SourceType.OTHER, EvidenceTier.C


def organization_name(result: SearchResult) -> str:
    """The publisher if known, otherwise the website's host (without 'www.')."""
    if result.publisher and result.publisher.strip():
        return result.publisher.strip()
    host = urlparse(result.url).hostname or result.url
    return host.removeprefix("www.")


def split_snippet(snippet: str) -> tuple[str, str]:
    """
    Split a snippet into (problem addressed, relevant insight).

    Search snippets usually open with what the page is about (the problem)
    and follow with detail (the insight). A one-sentence snippet is used for both.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snippet.strip()) if s.strip()]
    if len(sentences) == 1:
        return sentences[0], sentences[0]
    return sentences[0], " ".join(sentences[1:])


_TIER_PHRASE = {
    EvidenceTier.A: "Strong evidence (Tier A)",
    EvidenceTier.B: "Supporting evidence (Tier B)",
    EvidenceTier.C: "Discovery lead only (Tier C) — confirm with stronger sources",
}

_TYPE_PHRASE = {
    SourceType.STARTUP: "a startup building a product around this problem",
    SourceType.COMPANY: "an established organization investing in this problem",
    SourceType.GOVERNMENT_INITIATIVE: "an official government effort on this problem",
    SourceType.GOVERNMENT_REPORT: "an official assessment documenting this problem",
    SourceType.OFFICIAL_PROGRAM: "an official, funded programme targeting this problem",
    SourceType.NEWS: "recent coverage showing the problem is current",
    SourceType.RESEARCH_PAPER: "published research studying this problem",
    SourceType.UNIVERSITY_RESEARCH: "active university research on this problem",
    SourceType.PUBLIC_CHALLENGE: "an open challenge actively asking for solutions",
    SourceType.OPEN_SOURCE: "existing open-source work a project could build on",
    SourceType.DATASET: "data that a student project could realistically use",
    SourceType.INDUSTRY_REPORT: "an industry analysis describing the problem",
    SourceType.OTHER: "a lead pointing to where the problem is discussed",
}


def why_it_matters(tier: EvidenceTier, source_type: SourceType, industry: str, branch: str) -> str:
    """e.g. 'Strong evidence (Tier A): an official, funded programme targeting this problem in Navy (Defense).'"""
    return f"{_TIER_PHRASE[tier]}: {_TYPE_PHRASE[source_type]} in {branch} ({industry})."
