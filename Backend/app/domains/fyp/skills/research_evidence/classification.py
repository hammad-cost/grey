"""
Turning a raw search result into Project Brain evidence — with simple rules, no AI.

1. classify()          → source type + evidence tier (product blueprint §11)
2. organization_name() → who is behind the source
3. split_snippet()     → problem addressed + relevant insight
4. why_it_matters()    → a plain sentence explaining the source's value

How a source is classified (first matching rule wins):

  Part 1 — exact site lists (sources.py, editable). High confidence.
    official data portals                         dataset           A
    government / international bodies             initiative, report, programme, challenge, dataset  A
    listed news outlets                           news              B
    preprint servers (arXiv, SSRN, …)             research paper    B
    peer-reviewed publishers (IEEE, Springer, …)  research paper    A
    startup directories (YC, Product Hunt, …)     startup           C
    blogs, forums, social media                   other             C
    community datasets (Kaggle, Hugging Face)     dataset           B
    open-source hosts (GitHub, GitLab)            open source       B

  Part 2 — word clues for sites not on any list (also how the mock's sample
  sites are recognised). Only the site name and publisher are used — never
  the headline, so "Wall Street Journal" can't become a research paper and a
  title mentioning "accelerator" can't make a company page a directory.
    universities (.edu, .ac.)                     university research  B
    "news", "times" in the site name              news                 B
    industry / market reports, whitepapers        industry report      B
    an organization's own website                 startup / company    A
    anything else                                 other                C

Limitation: rules can't truly judge reputation; the lists in sources.py are
the place to improve that.
"""
import html
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from app.core.brain.schemas import EvidenceTier, ResearchCategory, SourceType
from app.core.tools.search import SearchResult
from app.domains.fyp.skills.research_evidence.sources import (
    COMMUNITY_DATASET_SITES,
    DISCUSSION_SITES,
    GOVERNMENT_SUFFIXES,
    INTERNATIONAL_BODIES,
    NEWS_OUTLETS,
    OFFICIAL_DATA_PORTALS,
    OPEN_SOURCE_SITES,
    PEER_REVIEWED_PUBLISHERS,
    PREPRINT_SERVERS,
    STARTUP_DIRECTORIES,
    host_in,
)


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

    def on(self, *lists: list[str]) -> bool:
        """The site is on one of the lists in sources.py."""
        return any(host_in(self.host, domains) for domains in lists)


def _is_government(page: _Page) -> bool:
    host = page.host
    return (
        any(host.endswith(suffix) or f"{suffix}." in host for suffix in GOVERNMENT_SUFFIXES)
        or host.startswith("gov.")
        or page.on(INTERNATIONAL_BODIES)
    )


def _is_university(page: _Page) -> bool:
    return any(page.host.endswith(s) or f"{s}." in page.host for s in (".edu", ".ac"))


# (does this rule match?, source type, tier) — checked top to bottom, first match wins.
_RULES: list[tuple[Callable[[_Page], bool], SourceType, EvidenceTier]] = [
    # ── Part 1: exact site lists ──────────────────────────────────────────────
    (lambda p: p.on(OFFICIAL_DATA_PORTALS), SourceType.DATASET, EvidenceTier.A),
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
    (lambda p: p.on(NEWS_OUTLETS), SourceType.NEWS, EvidenceTier.B),
    (lambda p: p.on(PREPRINT_SERVERS), SourceType.RESEARCH_PAPER, EvidenceTier.B),
    (lambda p: p.on(PEER_REVIEWED_PUBLISHERS), SourceType.RESEARCH_PAPER, EvidenceTier.A),
    (lambda p: p.on(STARTUP_DIRECTORIES), SourceType.STARTUP, EvidenceTier.C),
    (lambda p: p.on(DISCUSSION_SITES), SourceType.OTHER, EvidenceTier.C),
    (lambda p: p.on(COMMUNITY_DATASET_SITES), SourceType.DATASET, EvidenceTier.B),
    (lambda p: p.on(OPEN_SOURCE_SITES), SourceType.OPEN_SOURCE, EvidenceTier.B),

    # ── Part 2: word clues (site name and publisher only) ─────────────────────
    (lambda p: p.site_is("arxiv", "preprint"), SourceType.RESEARCH_PAPER, EvidenceTier.B),
    (lambda p: p.site_is("doi.org", "journal", "peer-reviewed"),
     SourceType.RESEARCH_PAPER, EvidenceTier.A),
    (_is_university, SourceType.UNIVERSITY_RESEARCH, EvidenceTier.B),
    (lambda p: p.site_is("directory", "aggregator", "accelerator"),
     SourceType.STARTUP, EvidenceTier.C),
    (lambda p: p.host.startswith("blog.") or "/blog" in p.path or p.site_is("blog", "forum"),
     SourceType.OTHER, EvidenceTier.C),
    (lambda p: p.category == ResearchCategory.DATASETS or p.site_is("dataset"),
     SourceType.DATASET, EvidenceTier.B),
    (lambda p: p.site_is("news", "times"), SourceType.NEWS, EvidenceTier.B),
    (lambda p: p.mentions("industry report", "market report", "whitepaper"),
     SourceType.INDUSTRY_REPORT, EvidenceTier.B),
    (lambda p: p.category == ResearchCategory.ORGANIZATIONS and p.site_is("startup"),
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


# ── Organization ──────────────────────────────────────────────────────────────

# A Google Scholar publication line: "J Smith, A Lee - IEEE Access, 2024 - ieeexplore.ieee.org"
_SCHOLAR_LINE = re.compile(r"^.+?\s-\s(?P<venue>.+?)\s-\s\S+$")
_YEAR_SUFFIX = re.compile(r",?\s*(19|20)\d{2}\s*$")


def _looks_like_a_link(text: str) -> bool:
    """e.g. "www.navy.mil › programme" or "harbor-ai.com" — a displayed link, not a name."""
    return "›" in text or (" " not in text and "." in text)


def organization_name(result: SearchResult) -> str:
    """
    Who is behind the source:
      - a Scholar publication line → the journal / venue ("IEEE Access")
      - a real publisher name → as given ("Reuters", "Harbor AI")
      - otherwise → the website's host without "www." ("navy.mil")
    """
    publisher = (result.publisher or "").strip()
    match = _SCHOLAR_LINE.match(publisher)
    if match:
        venue = _YEAR_SUFFIX.sub("", match.group("venue")).strip()
        if venue:
            return venue
    if publisher and not _looks_like_a_link(publisher):
        return publisher
    host = urlparse(result.url).hostname or result.url
    return host.removeprefix("www.")


# ── Text ──────────────────────────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])")
# Snippets often start with the date: "Mar 3, 2026 — " or "3 days ago ... "
_LEADING_DATE = re.compile(
    r"^(?:\d+\s+\w+\s+ago|[A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4})\s*[—–\-·.:]+\s*"
)


def clean_snippet(text: str) -> str:
    """Remove HTML, decode entities (&amp; → &), drop a leading date and tidy spaces."""
    text = html.unescape(_TAG.sub(" ", text))
    text = " ".join(text.split())
    text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)      # "congestion ." → "congestion."
    return _LEADING_DATE.sub("", text).strip()


def split_snippet(snippet: str) -> tuple[str, str]:
    """
    Split a snippet into (problem addressed, relevant insight).

    Search snippets usually open with what the page is about (the problem)
    and follow with detail (the insight). A one-sentence snippet is used for both.
    The snippet is cleaned first (HTML, entities, a leading date).
    """
    snippet = clean_snippet(snippet) or snippet.strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snippet) if s.strip()]
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
