"""
The second search hop: from startup directory listings to startups' own websites.

Product blueprint §11: directories and accelerator profiles are discovery
evidence (Tier C); the official startup website is primary evidence (Tier A).
So Grey:
  1. reads startup names from directory result titles, e.g.
       "Harbor AI: AI for ship monitoring | Y Combinator"   → "Harbor AI"
       "Harbor AI - Crunchbase Company Profile & Funding"   → "Harbor AI"
       "Top 10 maritime startups in 2026 | StartupBlink"    → (a list, skipped)
  2. searches each name, and keeps the result that is clearly the startup's
     own site — not a directory, news site, journal, government page or blog.

Plain rules, no AI. They can miss some names or pick none; that only means
fewer Tier A sources, never a wrong one marked as official without a match.
"""
import re
from urllib.parse import urlparse

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

_SEPARATORS = re.compile(r"\s+[|–—-]\s+|:\s+")
# Words that mean the title is a list, an article or a profile page, not a name.
_NOT_A_NAME = {
    "top", "best", "list", "startups", "startup", "companies", "company", "directory",
    "ranking", "funding", "profile", "case", "study", "how", "why", "what", "guide",
    "report", "news", "jobs", "investors", "overview",
}
MAX_NAME_WORDS = 5

# Sites that are never a startup's own website.
_NOT_OFFICIAL = (
    STARTUP_DIRECTORIES + NEWS_OUTLETS + DISCUSSION_SITES + PEER_REVIEWED_PUBLISHERS
    + PREPRINT_SERVERS + OFFICIAL_DATA_PORTALS + COMMUNITY_DATASET_SITES
    + OPEN_SOURCE_SITES + INTERNATIONAL_BODIES
)


def _squash(text: str) -> str:
    """Lower-case letters and digits only: "Harbor-AI.com" → "harboraicom"."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def startup_name_from_title(title: str, industry: str, branch: str) -> str | None:
    """The startup name at the start of a directory result title, or None if it isn't one."""
    name = _SEPARATORS.split(title.strip(), maxsplit=1)[0].strip(" .,'\"")
    words = name.split()
    if not words or len(words) > MAX_NAME_WORDS or len(name) < 2:
        return None
    if any(word.lower().strip(".,") in _NOT_A_NAME for word in words):
        return None
    if words[0][0].isdigit():                          # "10 startups to watch"
        return None
    if _squash(name) in (_squash(industry), _squash(branch)):
        return None
    return name


def startup_names(results: list[SearchResult], industry: str, branch: str, limit: int) -> list[str]:
    """Distinct startup names from directory results, in the order found, at most `limit`."""
    names: list[str] = []
    seen: set[str] = set()
    for result in results:
        name = startup_name_from_title(result.title, industry, branch)
        if name and _squash(name) not in seen:
            seen.add(_squash(name))
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _is_government(host: str) -> bool:
    return any(host.endswith(s) or f"{s}." in host for s in GOVERNMENT_SUFFIXES) or host.startswith("gov.")


def official_site(results: list[SearchResult], startup_name: str) -> SearchResult | None:
    """
    The result that is the startup's own website, or None.

    It must not be a known directory / news / research / government / social site,
    and the startup's name must appear in the web address (e.g. "Harbor AI" →
    harbor-ai.com, harborai.io, app.harbor.ai).
    """
    wanted = _squash(startup_name)
    for result in results:
        host = (urlparse(result.url).hostname or "").lower()
        if not host or host_in(host, _NOT_OFFICIAL) or _is_government(host):
            continue
        if wanted and wanted in _squash(host):
            return result
    return None
