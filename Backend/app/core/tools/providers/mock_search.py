"""
MockSearchProvider — realistic, deterministic, clearly fake search results.

Used in Release 0.2 so the whole research pipeline can be built and tested
without a search vendor, an API key, or any cost.

How it stays honest:
  - Every URL uses the reserved ".example" domain (RFC 2606). These links can
    never point at a real website, so sample results can't be mistaken for
    real evidence. The UI also shows a "Sample data" badge for provider "mock".
  - Organizations are invented, generic names — never real companies.

How it stays realistic:
  - It returns only what real search APIs return (title, url, snippet,
    publisher, date) — nothing a real provider couldn't give us.
  - Each snippet reads like a real one: a sentence about the problem,
    then a sentence with an insight.
  - Hosts look like real ones (".gov.example", ".edu.example", …) so the
    evidence-tier rules can be tested against them.

How it chooses results:
  - The topic is the first "quoted phrase" in the query (or the whole query).
  - The query's focus picks which templates are used.
  - The same query always returns the same results, in the same order.
"""
import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.tools.search import SearchFocus, SearchProvider, SearchQuery, SearchResult


@dataclass(frozen=True)
class _Template:
    """One fake page. {topic} and {slug} are filled in from the query."""
    host: str
    path: str
    title: str
    publisher: str
    problem: str      # first snippet sentence: the problem the page is about
    insight: str      # second snippet sentence: what the page tells us
    dated: bool = True


_TEMPLATES: dict[SearchFocus, list[_Template]] = {
    SearchFocus.COMPANIES: [
        _Template(
            host="www.northwind-analytics.example",
            path="/solutions/{slug}",
            title="Northwind Analytics — AI monitoring for {topic}",
            publisher="Northwind Analytics (sample startup)",
            problem="Teams working in {topic} still review large volumes of operational data by hand, so important warning signs are often noticed too late.",
            insight="The startup offers automated anomaly alerts and reports that early customers cut manual review time significantly.",
        ),
        _Template(
            host="www.meridian-systems.example",
            path="/products/{slug}-platform",
            title="Meridian Systems launches a predictive platform for {topic}",
            publisher="Meridian Systems (sample company)",
            problem="Organizations in {topic} struggle to predict equipment failures and demand peaks, which leads to costly unplanned downtime.",
            insight="The company combines historical records with live sensor data to forecast problems days in advance.",
        ),
        _Template(
            host="www.clearpath-labs.example",
            path="/case-studies/{slug}",
            title="Case study: reducing errors in {topic} workflows",
            publisher="ClearPath Labs (sample startup)",
            problem="Data in {topic} is spread across disconnected systems, so decision-makers rarely see a complete, up-to-date picture.",
            insight="Integrating sources into one dashboard and adding simple machine-learning checks reduced reporting errors in a pilot deployment.",
        ),
        _Template(
            host="startups.directory.example",
            path="/category/{slug}",
            title="Top emerging startups in {topic}",
            publisher="Startup Directory (sample aggregator)",
            problem="Many young companies in {topic} target the same bottleneck: slow, manual analysis of growing datasets.",
            insight="The directory lists early-stage teams applying computer vision, forecasting and decision-support tools to the area.",
            dated=False,
        ),
    ],
    SearchFocus.GOVERNMENT: [
        _Template(
            host="www.innovation-agency.gov.example",
            path="/programmes/{slug}",
            title="National {topic} Modernisation Programme",
            publisher="National Innovation Agency (sample government body)",
            problem="Public services related to {topic} depend on manual processes that cannot keep up with rising demand.",
            insight="The programme funds pilot projects that apply data analytics and AI to improve speed and accuracy.",
        ),
        _Template(
            host="www.audit-office.gov.example",
            path="/reports/{slug}-review",
            title="Review of digital capability in {topic}",
            publisher="Public Audit Office (sample government body)",
            problem="The review found that poor data quality and limited automation in {topic} cause delays and avoidable costs.",
            insight="It recommends investment in data standards, monitoring tools and staff training over the next three years.",
        ),
        _Template(
            host="challenges.gov.example",
            path="/open-challenges/{slug}",
            title="Open innovation challenge: {topic}",
            publisher="Government Challenge Platform (sample)",
            problem="Agencies working on {topic} are asking for practical tools that detect issues earlier with limited staff.",
            insight="The challenge invites student and startup teams to submit working prototypes for evaluation.",
        ),
    ],
    SearchFocus.RESEARCH: [
        _Template(
            host="journals.research.example",
            path="/articles/{slug}-machine-learning",
            title="Machine learning approaches for {topic}: a systematic review",
            publisher="Journal of Applied Computing (sample peer-reviewed journal)",
            problem="Published methods for {topic} are often evaluated on small, private datasets, which makes results hard to reproduce.",
            insight="The review identifies anomaly detection and forecasting as the most promising techniques and calls for open benchmarks.",
        ),
        _Template(
            host="www.cs.university.edu.example",
            path="/research/{slug}",
            title="University lab develops early-warning model for {topic}",
            publisher="Department of Computer Science, Example University (sample)",
            problem="Existing tools for {topic} react to problems after they happen rather than predicting them.",
            insight="Researchers report that a lightweight model trained on public data gave useful early warnings in tests.",
        ),
        _Template(
            host="preprints.archive.example",
            path="/abs/{slug}-2026",
            title="Towards explainable decision support in {topic}",
            publisher="Preprint Archive (sample)",
            problem="Practitioners in {topic} hesitate to trust automated recommendations they cannot understand.",
            insight="The authors propose an explainable model that shows which factors drove each recommendation.",
        ),
    ],
    SearchFocus.DATASETS: [
        _Template(
            host="data.open-portal.gov.example",
            path="/datasets/{slug}-records",
            title="{topic} open records dataset",
            publisher="Open Government Data Portal (sample)",
            problem="Researchers and students working on {topic} lack well-documented, openly licensed data.",
            insight="The portal publishes several years of anonymised records with a documented schema and an open licence.",
        ),
        _Template(
            host="datasets.ml-hub.example",
            path="/{slug}-benchmark",
            title="{topic} benchmark dataset for machine learning",
            publisher="ML Dataset Hub (sample community repository)",
            problem="Comparing models for {topic} is difficult without a shared, labelled benchmark.",
            insight="The community dataset provides labelled examples and a baseline model for comparison.",
        ),
    ],
    SearchFocus.NEWS: [
        _Template(
            host="www.tech-times.example",
            path="/news/{slug}-ai-adoption",
            title="Why {topic} is turning to AI",
            publisher="Tech Times (sample news site)",
            problem="Organizations in {topic} face growing workloads and skills shortages that manual processes can't absorb.",
            insight="Industry leaders interviewed expect automation and analytics budgets in the area to grow over the next two years.",
        ),
        _Template(
            host="blog.industry-insights.example",
            path="/posts/{slug}-trends",
            title="Five trends shaping {topic}",
            publisher="Industry Insights Blog (sample)",
            problem="Practitioners in {topic} report that data overload is now a bigger challenge than data scarcity.",
            insight="The post highlights real-time monitoring and predictive maintenance as fast-growing areas.",
            dated=False,
        ),
    ],
}

# GENERAL searches draw one result from each focus in turn.
_GENERAL_ORDER = [
    SearchFocus.COMPANIES,
    SearchFocus.GOVERNMENT,
    SearchFocus.RESEARCH,
    SearchFocus.NEWS,
    SearchFocus.DATASETS,
]


def _topic_from(text: str) -> str:
    """The first "quoted phrase" in the query, or the whole query if there are no quotes."""
    match = re.search(r'"([^"]+)"', text)
    return (match.group(1) if match else text).strip()


def _slug(topic: str) -> str:
    """'Fraud Detection' → 'fraud-detection'."""
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "topic"


def _stable_date(key: str) -> date:
    """A date between 2024-01-01 and about 2026-06, always the same for the same key."""
    days = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 900
    return date(2024, 1, 1) + timedelta(days=days)


def _templates_for(focus: SearchFocus) -> list[_Template]:
    if focus != SearchFocus.GENERAL:
        return _TEMPLATES[focus]
    # Interleave: first template of each focus, then second of each, …
    longest = max(len(t) for t in _TEMPLATES.values())
    return [
        _TEMPLATES[f][i]
        for i in range(longest)
        for f in _GENERAL_ORDER
        if i < len(_TEMPLATES[f])
    ]


class MockSearchProvider(SearchProvider):
    """A fake search provider for development and tests. See the module docstring."""

    name = "mock"

    def __init__(self, delay_ms: int = 0) -> None:
        # A small pause per search makes progress visible in the UI during development.
        # Tests use the default of 0 so they stay fast.
        self._delay_seconds = max(delay_ms, 0) / 1000

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        topic = _topic_from(query.text)
        slug = _slug(topic)

        results = []
        for template in _templates_for(query.focus)[: query.max_results]:
            url = f"https://{template.host}{template.path.format(slug=slug)}"
            results.append(
                SearchResult(
                    title=template.title.format(topic=topic),
                    url=url,
                    snippet=(
                        template.problem.format(topic=topic)
                        + " "
                        + template.insight.format(topic=topic)
                    ),
                    publisher=template.publisher,
                    published_date=_stable_date(url) if template.dated else None,
                )
            )
        return results
