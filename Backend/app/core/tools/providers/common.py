"""
Small helpers shared by the real search adapters (SerpAPI, Tavily, …).

Vendors return dates and results in slightly different, sometimes messy
shapes. These helpers turn them into clean SearchResult objects and quietly
skip anything unusable (no link, no text), instead of failing the search.
"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.core.tools.search import SearchResult

_RELATIVE = re.compile(r"^(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago$", re.IGNORECASE)
_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y")
# Longest text kept from a vendor field (the skill shortens further if it needs to).
MAX_TEXT = 1_000


def parse_date(value: object, today: date | None = None) -> date | None:
    """
    Best-effort date from a vendor field: "2026-03-01", "2026-03-01T10:00:00Z",
    "Mar 1, 2026", "3 days ago", … Unknown formats give None (never a guess).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    today = today or date.today()

    match = _RELATIVE.match(text)
    if match:
        amount, unit = int(match.group(1)), match.group(2).lower()
        days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}[unit] * amount
        return today - timedelta(days=days)

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_text(value: object) -> str:
    """Collapse whitespace and cap the length. Non-text becomes ''."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_TEXT]


def make_result(
    *,
    title: object,
    url: object,
    snippet: object,
    publisher: object = None,
    published_date: date | None = None,
    provider: str,
) -> SearchResult | None:
    """Build a SearchResult, or None if the item is missing a title, a real link or any text."""
    title_text = clean_text(title)
    snippet_text = clean_text(snippet)
    if not title_text or not snippet_text or not isinstance(url, str):
        return None
    try:
        return SearchResult(
            title=title_text,
            url=url.strip(),
            snippet=snippet_text,
            publisher=clean_text(publisher) or None,
            published_date=published_date,
            provider=provider,
        )
    except ValidationError:
        return None          # e.g. not an http(s) link


def recency_bucket(days: int | None) -> str | None:
    """Turn 'last N days' into the coarse buckets search APIs offer: day / week / month / year."""
    if days is None:
        return None
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


def on_sites(url: str, domains: list[str]) -> bool:
    """True if the link is on one of these sites or their subdomains (e.g. www.ycombinator.com)."""
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in (d.strip().lower() for d in domains) if d)
