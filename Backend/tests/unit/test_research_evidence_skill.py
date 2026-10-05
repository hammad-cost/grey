"""
Tests for ResearchEvidenceSkill.

Most tests use a small fake search provider so each behaviour can be checked
precisely. A few use the real MockSearchProvider end-to-end, including saving
the result through the Project Brain repository.
"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.brain.models import Base
from app.core.brain.repository import WorkspaceBrainRepository
from app.core.brain.schemas import EvidenceSource, EvidenceTier, ResearchCategory
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import (
    SearchFocus,
    SearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchResult,
)
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.research_evidence import (
    ResearchEvidenceInput,
    ResearchEvidenceOutput,
    ResearchEvidenceSkill,
    ResearchPhase,
    ResearchProgress,
)

NAVY = ResearchEvidenceInput(workspace_id="ws-1", industry="Defense", branch="Navy")


class FakeSearch(SearchProvider):
    """Returns canned results per search focus and records every query it receives."""

    name = "fake"

    def __init__(self, results: dict[SearchFocus, list[SearchResult]] | None = None,
                 fail_on: SearchFocus | None = None):
        self.results = results or {}
        self.fail_on = fail_on
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.queries.append(query)
        if query.focus == self.fail_on:
            raise SearchProviderError("provider down")
        return self.results.get(query.focus, [])[: query.max_results]


def page(host: str, publisher: str = "Example Org", published: date | None = None,
         title: str | None = None) -> SearchResult:
    return SearchResult(
        title=title or f"Page on {host}",
        url=f"https://{host}/page",
        snippet="Operators struggle to spot unusual vessels. Automated alerts helped in trials.",
        publisher=publisher,
        published_date=published,
    )


async def run(skill: ResearchEvidenceSkill, input: ResearchEvidenceInput = NAVY):
    """Run the skill and collect its progress updates."""
    progress: list[ResearchProgress] = []

    async def collect(update: ResearchProgress) -> None:
        progress.append(update)

    output = await skill.execute(input, on_progress=collect)
    return output, progress


# ── Contract ──────────────────────────────────────────────────────────────────

def test_metadata():
    skill = ResearchEvidenceSkill(FakeSearch())
    assert skill.metadata.name == "research_evidence"
    assert skill.metadata.requires_human_approval is False


@pytest.mark.parametrize("bad", [dict(industry=""), dict(branch=""), dict(max_sources_per_category=0),
                                 dict(max_sources_per_category=11)])
def test_input_is_validated(bad):
    with pytest.raises(Exception):
        ResearchEvidenceInput(**{**NAVY.model_dump(), **bad})


async def test_returns_typed_output_with_complete_evidence():
    search = FakeSearch({SearchFocus.GOVERNMENT: [page("www.navy.mil", "Navy Office")]})
    output, _ = await run(ResearchEvidenceSkill(search))

    assert isinstance(output, ResearchEvidenceOutput)
    [source] = output.sources
    assert isinstance(source, EvidenceSource)
    assert source.organization == "Navy Office"
    assert source.problem_addressed == "Operators struggle to spot unusual vessels."
    assert source.relevant_insight == "Automated alerts helped in trials."
    assert "Navy (Defense)" in source.why_it_matters
    assert source.evidence_tier == EvidenceTier.A
    assert source.research_category == ResearchCategory.OFFICIAL_SOURCES
    assert source.provider == "fake"
    assert "Navy" in source.query


async def test_works_without_a_progress_callback():
    output = await ResearchEvidenceSkill(FakeSearch()).execute(NAVY)
    assert output.sources == []


# ── Queries ───────────────────────────────────────────────────────────────────

async def test_runs_the_research_plan_in_order():
    search = FakeSearch()
    output, _ = await run(ResearchEvidenceSkill(search))

    assert [q.focus for q in search.queries] == [
        SearchFocus.COMPANIES, SearchFocus.NEWS,      # organizations
        SearchFocus.GOVERNMENT,                       # official sources
        SearchFocus.RESEARCH,                         # research
        SearchFocus.DATASETS,                         # datasets
    ]
    assert all(q.text.startswith('"Navy" Defense') for q in search.queries)
    assert output.queries_run == [q.text for q in search.queries]


async def test_max_sources_per_category_is_passed_to_searches():
    search = FakeSearch()
    await run(ResearchEvidenceSkill(search), NAVY.model_copy(update={"max_sources_per_category": 3}))
    assert {q.max_results for q in search.queries} == {3}


# ── Normalization: de-duplication, caps, ranking ──────────────────────────────

async def test_same_url_is_kept_only_once():
    shared = page("www.meridian.example", "Meridian Systems")
    search = FakeSearch({SearchFocus.COMPANIES: [shared], SearchFocus.NEWS: [shared],
                         SearchFocus.RESEARCH: [shared]})
    output, _ = await run(ResearchEvidenceSkill(search))

    assert len(output.sources) == 1
    assert output.sources[0].research_category == ResearchCategory.ORGANIZATIONS   # first finder wins


async def test_each_category_keeps_only_its_strongest_sources():
    # Organizations: 2 company pages (Tier A) + 2 news (B) + 2 blogs (C), cap 3 → the 2 A's and 1 B.
    search = FakeSearch({
        SearchFocus.COMPANIES: [page("blog.one.example"), page("www.co-a.example"), page("www.co-b.example")],
        SearchFocus.NEWS: [page("blog.two.example"), page("www.reuters.com"), page("www.bbc.co.uk")],
    })
    output, _ = await run(ResearchEvidenceSkill(search), NAVY.model_copy(update={"max_sources_per_category": 3}))

    assert [s.evidence_tier for s in output.sources] == [EvidenceTier.A, EvidenceTier.A, EvidenceTier.B]


async def test_sources_are_returned_strongest_first():
    search = FakeSearch({
        SearchFocus.NEWS: [page("www.reuters.com", published=date(2026, 1, 1), title="B news")],
        SearchFocus.GOVERNMENT: [
            page("old.agency.gov", published=date(2024, 1, 1), title="A old"),
            page("new.agency.gov", published=date(2026, 5, 1), title="A new"),
            page("undated.agency.gov", title="A undated"),
        ],
        SearchFocus.RESEARCH: [page("medium.com", title="C blog")],
    })
    output, _ = await run(ResearchEvidenceSkill(search))

    assert [s.title for s in output.sources] == ["A new", "A old", "A undated", "B news", "C blog"]


# ── Progress ──────────────────────────────────────────────────────────────────

async def test_progress_follows_the_research_steps():
    output, progress = await run(ResearchEvidenceSkill(MockSearchProvider()))

    assert [(p.phase, p.category) for p in progress] == [
        (ResearchPhase.SEARCHING_SOURCES, ResearchCategory.ORGANIZATIONS),
        (ResearchPhase.SOURCES_FOUND, ResearchCategory.ORGANIZATIONS),
        (ResearchPhase.SEARCHING_SOURCES, ResearchCategory.OFFICIAL_SOURCES),
        (ResearchPhase.SOURCES_FOUND, ResearchCategory.OFFICIAL_SOURCES),
        (ResearchPhase.SEARCHING_SOURCES, ResearchCategory.RESEARCH),
        (ResearchPhase.SOURCES_FOUND, ResearchCategory.RESEARCH),
        (ResearchPhase.SEARCHING_SOURCES, ResearchCategory.DATASETS),
        (ResearchPhase.SOURCES_FOUND, ResearchCategory.DATASETS),
        (ResearchPhase.EVALUATING_EVIDENCE, None),
    ]
    # Counts only ever grow, and end at the final totals.
    counts = [p.sources_found for p in progress]
    assert counts == sorted(counts)
    assert progress[-1].sources_found == output.summary.total_sources
    assert progress[-1].high_quality_sources == output.summary.high_quality_count


async def test_progress_labels_are_safe_activity_only():
    _, progress = await run(ResearchEvidenceSkill(MockSearchProvider()))
    assert {p.label for p in progress} == {
        "Identifying relevant organizations",
        "Reviewing authoritative sources",
        "Checking research",
        "Checking datasets",
        "Evaluating evidence quality",
    }


# ── Failure ───────────────────────────────────────────────────────────────────

async def test_provider_failure_is_raised_and_research_stops():
    search = FakeSearch(fail_on=SearchFocus.GOVERNMENT)
    progress: list[ResearchProgress] = []

    async def collect(update):
        progress.append(update)

    with pytest.raises(SearchProviderError):
        await ResearchEvidenceSkill(search).execute(NAVY, on_progress=collect)

    assert search.queries[-1].focus == SearchFocus.GOVERNMENT     # no searches after the failure
    assert progress[-1].phase == ResearchPhase.SEARCHING_SOURCES   # never reached "evaluating"


# ── Summary ───────────────────────────────────────────────────────────────────

async def test_summary_matches_the_sources():
    output, _ = await run(ResearchEvidenceSkill(MockSearchProvider()))
    s = output.summary

    assert s.total_sources == len(output.sources)
    assert sum(s.by_tier.values()) == s.total_sources
    assert sum(s.by_category.values()) == s.total_sources
    assert s.high_quality_count == s.by_tier[EvidenceTier.A]
    assert s.provider == "mock"


# ── End-to-end with the mock provider and the Project Brain ───────────────────

async def test_mock_research_gives_a_realistic_mix():
    output, _ = await run(ResearchEvidenceSkill(MockSearchProvider()))

    assert output.summary.total_sources >= 12
    assert all(output.summary.by_category[c] > 0 for c in ResearchCategory)
    assert all(output.summary.by_tier[t] > 0 for t in EvidenceTier)       # A, B and C all present
    assert all(".example/" in s.url for s in output.sources)


async def test_output_can_be_saved_to_the_project_brain():
    """The skill's evidence goes straight into the repository with no conversion."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
        repo = WorkspaceBrainRepository(session)
        await repo.create_workspace("ws-1")
        output, _ = await run(ResearchEvidenceSkill(MockSearchProvider()))

        run_record = await repo.start_research_run("ws-1", provider=output.summary.provider)
        done = await repo.complete_research_run(run_record.id, output.sources)

        assert done.sources_found == output.summary.total_sources
        assert done.high_quality_count == output.summary.high_quality_count
        assert len(await repo.list_evidence("ws-1")) == output.summary.total_sources
    await engine.dispose()


# ── Registry ──────────────────────────────────────────────────────────────────

def test_register_fyp_skills_adds_research_evidence():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())

    assert "research_evidence" in registry
    assert isinstance(registry.get("research_evidence"), ResearchEvidenceSkill)


def test_registering_twice_is_rejected():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())
    with pytest.raises(ValueError, match="already registered"):
        register_fyp_skills(registry, MockSearchProvider())
