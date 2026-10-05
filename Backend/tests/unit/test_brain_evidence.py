"""
Tests for evidence and research-run storage in the Project Brain.

Uses an in-memory SQLite database so no files are created on disk and
tests run fast without affecting the real grey.db file.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.brain.models import Base, ResearchRunRecord
from app.core.brain.repository import ResearchAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    EvidenceSource,
    EvidenceTier,
    ResearchCategory,
    ResearchStatus,
    SourceType,
)

# ── Shared test database setup ────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session() -> AsyncSession:
    """A fresh in-memory database and session for each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> WorkspaceBrainRepository:
    return WorkspaceBrainRepository(session)


def make_source(**overrides) -> EvidenceSource:
    """A complete, valid piece of evidence. Override any field per test."""
    fields = dict(
        title="Maritime Domain Awareness Programme",
        organization="Example Maritime Agency",
        source_type=SourceType.GOVERNMENT_INITIATIVE,
        published_date=date(2026, 3, 1),
        url="https://example.com/maritime-awareness",
        problem_addressed="Unusual vessel behaviour is hard to spot manually in large AIS data streams.",
        relevant_insight="The agency funds automated anomaly detection for coastal monitoring.",
        why_it_matters="Official initiative showing an active, funded need in naval surveillance.",
        evidence_tier=EvidenceTier.A,
        research_category=ResearchCategory.OFFICIAL_SOURCES,
        query="Navy maritime surveillance government initiative",
        provider="mock",
    )
    fields.update(overrides)
    return EvidenceSource(**fields)


async def new_project(repo: WorkspaceBrainRepository, workspace_id: str) -> None:
    """Create a project that has reached EVIDENCE_RESEARCH, like a real student journey."""
    await repo.create_workspace(workspace_id)
    await repo.apply_decision(workspace_id, "industry", "Defense")
    await repo.apply_decision(workspace_id, "branch", "Navy")


# ── EvidenceSource schema ─────────────────────────────────────────────────────

def test_evidence_source_accepts_all_blueprint_fields():
    source = make_source()
    assert source.evidence_tier == EvidenceTier.A
    assert source.problem_addressed.startswith("Unusual vessel")


def test_evidence_source_date_is_optional():
    assert make_source(published_date=None).published_date is None


@pytest.mark.parametrize(
    "field", ["title", "organization", "problem_addressed", "relevant_insight", "why_it_matters"]
)
def test_evidence_source_rejects_empty_text(field):
    with pytest.raises(ValidationError):
        make_source(**{field: ""})


def test_evidence_source_rejects_invalid_url():
    with pytest.raises(ValidationError):
        make_source(url="not a url")


def test_evidence_source_rejects_unknown_tier():
    with pytest.raises(ValidationError):
        make_source(evidence_tier="D")


# ── Research run lifecycle ────────────────────────────────────────────────────

async def test_new_project_has_no_research(repo):
    snapshot = await repo.create_workspace("ws-1")
    assert snapshot.research is None
    assert await repo.list_evidence("ws-1") == []


async def test_start_research_run(repo):
    await new_project(repo, "ws-1")

    run = await repo.start_research_run("ws-1", provider="mock")

    assert run.status == ResearchStatus.RUNNING
    assert run.provider == "mock"
    assert run.sources_found == 0
    snapshot = await repo.get_snapshot("ws-1")
    assert snapshot.research.id == run.id
    assert snapshot.research.status == ResearchStatus.RUNNING


async def test_start_research_run_unknown_project(repo):
    with pytest.raises(ValueError, match="not found"):
        await repo.start_research_run("ghost", provider="mock")


async def test_cannot_start_second_run_while_one_is_running(repo):
    await new_project(repo, "ws-1")
    await repo.start_research_run("ws-1", provider="mock")

    with pytest.raises(ResearchAlreadyRunningError):
        await repo.start_research_run("ws-1", provider="mock")


async def test_stale_running_run_does_not_block_a_new_run(repo, session):
    """A run left 'running' by a crash is marked failed once it is old enough."""
    await new_project(repo, "ws-1")
    old = await repo.start_research_run("ws-1", provider="mock")

    # Pretend the old run started an hour ago.
    record = await session.get(ResearchRunRecord, old.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()

    new = await repo.start_research_run("ws-1", provider="mock")

    assert new.status == ResearchStatus.RUNNING
    stale = await session.get(ResearchRunRecord, old.id)
    assert stale.status == ResearchStatus.FAILED.value
    assert "stale" in stale.error


async def test_complete_research_run_saves_evidence_and_counts(repo):
    await new_project(repo, "ws-1")
    run = await repo.start_research_run("ws-1", provider="mock")
    sources = [
        make_source(url="https://example.com/a", evidence_tier=EvidenceTier.A),
        make_source(url="https://example.com/b", evidence_tier=EvidenceTier.A),
        make_source(url="https://example.com/c", evidence_tier=EvidenceTier.B,
                    source_type=SourceType.NEWS),
    ]

    done = await repo.complete_research_run(run.id, sources)

    assert done.status == ResearchStatus.COMPLETE
    assert done.completed_at is not None
    assert done.sources_found == 3
    assert done.high_quality_count == 2       # Tier A only
    snapshot = await repo.get_snapshot("ws-1")
    assert snapshot.research.status == ResearchStatus.COMPLETE


async def test_stored_evidence_keeps_every_field(repo):
    await new_project(repo, "ws-1")
    run = await repo.start_research_run("ws-1", provider="mock")
    original = make_source()

    await repo.complete_research_run(run.id, [original])
    [stored] = await repo.list_evidence("ws-1")

    # Every blueprint field comes back exactly as saved, with proper enum types.
    assert stored.model_dump(include=set(EvidenceSource.model_fields)) == original.model_dump()
    assert stored.source_type is SourceType.GOVERNMENT_INITIATIVE
    assert stored.evidence_tier is EvidenceTier.A
    assert stored.workspace_id == "ws-1"
    assert stored.research_run_id == run.id
    assert stored.retrieved_at is not None


async def test_list_evidence_strongest_first(repo):
    """Order: Tier A → B → C, then newest first (undated last), then title."""
    await new_project(repo, "ws-1")
    run = await repo.start_research_run("ws-1", provider="mock")
    await repo.complete_research_run(run.id, [
        make_source(url="https://example.com/c", title="C source", evidence_tier=EvidenceTier.C),
        make_source(url="https://example.com/a-old", title="A old",
                    published_date=date(2024, 1, 1)),
        make_source(url="https://example.com/b", title="B source", evidence_tier=EvidenceTier.B),
        make_source(url="https://example.com/a-undated", title="A undated", published_date=None),
        make_source(url="https://example.com/a-new", title="A new",
                    published_date=date(2026, 6, 1)),
    ])

    titles = [s.title for s in await repo.list_evidence("ws-1")]

    assert titles == ["A new", "A old", "A undated", "B source", "C source"]


async def test_new_successful_run_replaces_previous_evidence(repo):
    await new_project(repo, "ws-1")
    first = await repo.start_research_run("ws-1", provider="mock")
    await repo.complete_research_run(first.id, [make_source(url="https://example.com/old")])

    second = await repo.start_research_run("ws-1", provider="mock")
    await repo.complete_research_run(second.id, [make_source(url="https://example.com/new")])

    evidence = await repo.list_evidence("ws-1")
    assert [s.url for s in evidence] == ["https://example.com/new"]
    assert evidence[0].research_run_id == second.id
    assert (await repo.get_latest_research_run("ws-1")).id == second.id


async def test_failed_run_keeps_previous_evidence(repo):
    await new_project(repo, "ws-1")
    first = await repo.start_research_run("ws-1", provider="mock")
    await repo.complete_research_run(first.id, [make_source(url="https://example.com/kept")])

    second = await repo.start_research_run("ws-1", provider="mock")
    failed = await repo.fail_research_run(second.id, "Search provider unavailable")

    assert failed.status == ResearchStatus.FAILED
    assert failed.error == "Search provider unavailable"
    assert failed.completed_at is not None
    assert [s.url for s in await repo.list_evidence("ws-1")] == ["https://example.com/kept"]
    assert (await repo.get_snapshot("ws-1")).research.status == ResearchStatus.FAILED


async def test_duplicate_urls_are_rejected_and_nothing_is_saved(repo):
    await new_project(repo, "ws-1")
    run = await repo.start_research_run("ws-1", provider="mock")

    with pytest.raises(ValueError, match="duplicate"):
        await repo.complete_research_run(run.id, [
            make_source(url="https://example.com/same"),
            make_source(url="https://example.com/same", title="Another title"),
        ])

    assert await repo.list_evidence("ws-1") == []
    assert (await repo.get_latest_research_run("ws-1")).status == ResearchStatus.RUNNING


async def test_cannot_complete_a_run_that_is_not_running(repo):
    await new_project(repo, "ws-1")
    run = await repo.start_research_run("ws-1", provider="mock")
    await repo.fail_research_run(run.id, "boom")

    with pytest.raises(ValueError, match="not running"):
        await repo.complete_research_run(run.id, [make_source()])


async def test_unknown_run_id_raises(repo):
    with pytest.raises(ValueError, match="not found"):
        await repo.complete_research_run("no-such-run", [])
    with pytest.raises(ValueError, match="not found"):
        await repo.fail_research_run("no-such-run", "boom")


async def test_evidence_is_isolated_per_project(repo):
    """Two projects can store the same URL, and never see each other's evidence."""
    for workspace_id in ("ws-1", "ws-2"):
        await new_project(repo, workspace_id)
        run = await repo.start_research_run(workspace_id, provider="mock")
        await repo.complete_research_run(run.id, [
            make_source(url="https://example.com/shared", title=f"Seen by {workspace_id}"),
        ])

    assert [s.title for s in await repo.list_evidence("ws-1")] == ["Seen by ws-1"]
    assert [s.title for s in await repo.list_evidence("ws-2")] == ["Seen by ws-2"]


async def test_release_01_decisions_untouched_by_research(repo):
    """Research storage must not change industry, branch, or workflow state."""
    await new_project(repo, "ws-1")
    before = await repo.get_snapshot("ws-1")

    run = await repo.start_research_run("ws-1", provider="mock")
    await repo.complete_research_run(run.id, [make_source()])
    after = await repo.get_snapshot("ws-1")

    assert (after.industry, after.branch, after.workflow_state) == (
        before.industry, before.branch, before.workflow_state
    )


async def test_database_has_the_new_tables(session):
    """create_all builds research_run and evidence_source alongside workspace_brain."""
    def table_names(sync_conn):
        from sqlalchemy import inspect
        return set(inspect(sync_conn).get_table_names())

    conn = await session.connection()
    names = await conn.run_sync(table_names)
    assert {"workspace_brain", "research_run", "evidence_source"} <= names
    # And the new table is empty on a fresh database.
    assert (await session.execute(select(ResearchRunRecord))).first() is None
