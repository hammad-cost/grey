"""
Tests for problem-option storage in the Project Brain (Release 0.3, Step 1).

Covers problem runs, saving the options a run produced (with the evidence
they cite), and the student's mandatory problem selection.

Uses an in-memory SQLite database so no files are created on disk.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.brain.models import Base, ProblemRunRecord
from app.core.brain.repository import (
    ProblemRunAlreadyRunningError,
    ProblemSelectionError,
    WorkspaceBrainRepository,
)
from app.core.brain.schemas import (
    EvidenceSource,
    EvidenceStrength,
    EvidenceTier,
    ProblemCandidate,
    ProblemEvidenceLink,
    ProblemRunStatus,
    ProblemStatus,
    ProblemTaskType,
    ResearchCategory,
    SourceType,
    StoredEvidenceSource,
    WorkflowState,
)

WS = "ws-navy"


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture
async def session() -> AsyncSession:
    """A fresh in-memory database and session for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> WorkspaceBrainRepository:
    return WorkspaceBrainRepository(session)


def make_source(n: int, tier: EvidenceTier = EvidenceTier.A) -> EvidenceSource:
    return EvidenceSource(
        title=f"Source {n}",
        organization=f"Organization {n}",
        source_type=SourceType.GOVERNMENT_INITIATIVE,
        published_date=date(2026, 1, n),
        url=f"https://example.com/source-{n}",
        problem_addressed=f"Problem addressed by source {n}.",
        relevant_insight=f"Insight from source {n}.",
        why_it_matters=f"Why source {n} matters.",
        evidence_tier=tier,
        research_category=ResearchCategory.OFFICIAL_SOURCES,
        query="Navy maritime surveillance",
        provider="mock",
    )


async def researched_project(
    repo: WorkspaceBrainRepository, workspace_id: str = WS
) -> tuple[str, list[StoredEvidenceSource]]:
    """A project at EVIDENCE_RESEARCH with a completed research run. Returns (run id, evidence)."""
    await repo.create_workspace(workspace_id)
    await repo.apply_decision(workspace_id, "industry", "Defense")
    await repo.apply_decision(workspace_id, "branch", "Navy")
    await repo.update_workflow_state(workspace_id, WorkflowState.EVIDENCE_RESEARCH)
    run = await repo.start_research_run(workspace_id, provider="mock")
    await repo.complete_research_run(
        run.id,
        [make_source(1, EvidenceTier.A), make_source(2, EvidenceTier.B), make_source(3, EvidenceTier.C)],
    )
    return run.id, await repo.list_evidence(workspace_id)


def make_candidate(evidence_ids: list[str], **overrides) -> ProblemCandidate:
    """A complete, valid problem option citing the given evidence."""
    fields = dict(
        title="Abnormal vessel movement detection",
        real_world_problem="Operators must monitor large volumes of vessel data by hand.",
        observed_solutions="Companies are building automated maritime surveillance platforms.",
        technical_problem="Detecting anomalous trajectories in AIS time series.",
        task_type=ProblemTaskType.ANOMALY_DETECTION,
        why_it_matters="Earlier detection improves maritime awareness.",
        possible_fyp_direction="Build a model that flags unusual vessel tracks in public AIS data.",
        evidence=[
            ProblemEvidenceLink(evidence_source_id=i, supporting_point=f"Point from {i}")
            for i in evidence_ids
        ],
        evidence_strength=EvidenceStrength(tier_a=1),
    )
    fields.update(overrides)
    return ProblemCandidate(**fields)


async def complete_with(repo, run_id: str, candidates: list[ProblemCandidate], **overrides):
    """Complete a problem run with sensible LLM metadata."""
    fields = dict(
        provider="fake", model="fake-model", prompt_version="v1",
        candidates_generated=len(candidates), rejection_summary={},
    )
    fields.update(overrides)
    return await repo.complete_problem_run(run_id, candidates, **fields)


async def project_with_options(repo, workspace_id: str = WS, titles=("Problem one", "Problem two", "Problem three")):
    """A project whose problem options have been saved. Returns the stored options."""
    research_id, evidence = await researched_project(repo, workspace_id)
    run = await repo.start_problem_run(workspace_id, research_id)
    ids = [e.id for e in evidence]
    await complete_with(repo, run.id, [make_candidate(ids[:2], title=t) for t in titles])
    return await repo.list_problem_candidates(workspace_id)


# ── ProblemCandidate schema ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "field", ["title", "real_world_problem", "observed_solutions", "technical_problem",
              "why_it_matters", "possible_fyp_direction"],
)
def test_problem_candidate_rejects_empty_text(field):
    with pytest.raises(ValidationError):
        make_candidate(["e1"], **{field: ""})


def test_problem_candidate_must_cite_evidence():
    with pytest.raises(ValidationError):
        make_candidate([])


def test_problem_candidate_rejects_unknown_task_type():
    with pytest.raises(ValidationError):
        make_candidate(["e1"], task_type="time_travel")


def test_problem_candidate_title_has_a_length_limit():
    with pytest.raises(ValidationError):
        make_candidate(["e1"], title="x" * 121)


# ── Problem runs ──────────────────────────────────────────────────────────────

async def test_new_project_has_no_problems(repo):
    await repo.create_workspace(WS)
    snapshot = await repo.get_snapshot(WS)

    assert snapshot.problem_run is None
    assert snapshot.selected_problem is None
    assert await repo.list_problem_candidates(WS) == []
    assert await repo.get_latest_problem_run(WS) is None


async def test_start_problem_run(repo):
    research_id, _ = await researched_project(repo)

    run = await repo.start_problem_run(WS, research_id)

    assert run.status == ProblemRunStatus.RUNNING
    assert run.research_run_id == research_id
    assert (await repo.get_snapshot(WS)).problem_run.id == run.id


async def test_start_problem_run_unknown_project(repo):
    with pytest.raises(ValueError):
        await repo.start_problem_run("does-not-exist", "any-run")


async def test_start_problem_run_needs_a_completed_research_run(repo):
    await repo.create_workspace(WS)
    research = await repo.start_research_run(WS, provider="mock")   # still running

    with pytest.raises(ValueError):
        await repo.start_problem_run(WS, research.id)


async def test_start_problem_run_rejects_another_projects_research(repo):
    other_research_id, _ = await researched_project(repo, "ws-other")
    await repo.create_workspace(WS)

    with pytest.raises(ValueError):
        await repo.start_problem_run(WS, other_research_id)


async def test_cannot_start_second_problem_run_while_one_is_running(repo):
    research_id, _ = await researched_project(repo)
    await repo.start_problem_run(WS, research_id)

    with pytest.raises(ProblemRunAlreadyRunningError):
        await repo.start_problem_run(WS, research_id)


async def test_stale_problem_run_does_not_block_a_new_run(repo, session):
    research_id, _ = await researched_project(repo)
    old = await repo.start_problem_run(WS, research_id)
    record = await session.get(ProblemRunRecord, old.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()

    new = await repo.start_problem_run(WS, research_id)

    assert new.id != old.id
    assert (await session.get(ProblemRunRecord, old.id)).status == "failed"


# ── Saving problem options ────────────────────────────────────────────────────

async def test_complete_problem_run_saves_options_in_rank_order(repo):
    research_id, evidence = await researched_project(repo)
    ids = [e.id for e in evidence]
    run = await repo.start_problem_run(WS, research_id)

    completed = await complete_with(
        repo, run.id,
        [make_candidate(ids[:1], title="Strongest"), make_candidate(ids[1:2], title="Second")],
        provider="groq", model="model-x", prompt_version="v2",
        candidates_generated=6, rejection_summary={"ungrounded": 3, "duplicate": 1},
    )

    assert completed.status == ProblemRunStatus.COMPLETE
    assert (completed.provider, completed.model, completed.prompt_version) == ("groq", "model-x", "v2")
    assert completed.candidates_generated == 6
    assert completed.candidates_kept == 2
    assert completed.rejection_summary == {"ungrounded": 3, "duplicate": 1}

    options = await repo.list_problem_candidates(WS)
    assert [(o.rank, o.title) for o in options] == [(1, "Strongest"), (2, "Second")]
    assert all(o.status == ProblemStatus.CANDIDATE for o in options)
    assert all(o.problem_run_id == run.id for o in options)


async def test_completing_moves_project_to_problem_options(repo):
    await project_with_options(repo)
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.PROBLEM_OPTIONS


async def test_stored_option_keeps_every_field_and_its_sources(repo):
    research_id, evidence = await researched_project(repo)
    by_tier = {e.evidence_tier: e for e in evidence}
    run = await repo.start_problem_run(WS, research_id)
    candidate = make_candidate(
        [by_tier[EvidenceTier.C].id, by_tier[EvidenceTier.A].id],
        evidence_strength=EvidenceStrength(tier_a=1, tier_c=1),
    )

    await complete_with(repo, run.id, [candidate])
    [stored] = await repo.list_problem_candidates(WS)

    for field in ("title", "real_world_problem", "observed_solutions", "technical_problem",
                  "task_type", "why_it_matters", "possible_fyp_direction", "evidence_strength"):
        assert getattr(stored, field) == getattr(candidate, field)

    # Sources come back with their details, strongest first.
    assert [s.evidence_tier for s in stored.evidence] == [EvidenceTier.A, EvidenceTier.C]
    source = stored.evidence[0]
    assert source.title == by_tier[EvidenceTier.A].title
    assert source.url == by_tier[EvidenceTier.A].url
    assert source.organization == by_tier[EvidenceTier.A].organization
    assert source.supporting_point == f"Point from {by_tier[EvidenceTier.A].id}"


async def test_options_cannot_cite_another_projects_evidence(repo):
    _, other_evidence = await researched_project(repo, "ws-other")
    research_id, _ = await researched_project(repo)
    run = await repo.start_problem_run(WS, research_id)

    with pytest.raises(ValueError, match="doesn't have"):
        await complete_with(repo, run.id, [make_candidate([other_evidence[0].id])])

    assert await repo.list_problem_candidates(WS) == []
    assert (await repo.get_latest_problem_run(WS)).status == ProblemRunStatus.RUNNING


async def test_options_cannot_cite_made_up_evidence(repo):
    research_id, _ = await researched_project(repo)
    run = await repo.start_problem_run(WS, research_id)

    with pytest.raises(ValueError):
        await complete_with(repo, run.id, [make_candidate(["invented-id"])])


async def test_an_option_cannot_cite_the_same_source_twice(repo):
    research_id, evidence = await researched_project(repo)
    run = await repo.start_problem_run(WS, research_id)

    with pytest.raises(ValueError, match="twice"):
        await complete_with(repo, run.id, [make_candidate([evidence[0].id, evidence[0].id])])


@pytest.mark.parametrize("count", [0, 6])
async def test_option_count_must_be_between_one_and_five(repo, count):
    research_id, evidence = await researched_project(repo)
    run = await repo.start_problem_run(WS, research_id)

    with pytest.raises(ValueError):
        await complete_with(repo, run.id, [make_candidate([evidence[0].id])] * count)


async def test_cannot_complete_a_problem_run_that_is_not_running(repo):
    research_id, evidence = await researched_project(repo)
    run = await repo.start_problem_run(WS, research_id)
    await repo.fail_problem_run(run.id, "boom")

    with pytest.raises(ValueError):
        await complete_with(repo, run.id, [make_candidate([evidence[0].id])])


async def test_unknown_problem_run_raises(repo):
    with pytest.raises(ValueError):
        await repo.fail_problem_run("no-such-run", "boom")


async def test_new_successful_run_replaces_previous_options(repo):
    await project_with_options(repo, titles=("Old one", "Old two"))
    research_id = (await repo.get_snapshot(WS)).research.id
    evidence_id = (await repo.list_evidence(WS))[0].id

    run = await repo.start_problem_run(WS, research_id)
    await complete_with(repo, run.id, [make_candidate([evidence_id], title="New one")])

    assert [o.title for o in await repo.list_problem_candidates(WS)] == ["New one"]


async def test_failed_run_keeps_previous_options(repo):
    await project_with_options(repo, titles=("Kept one", "Kept two"))
    research_id = (await repo.get_snapshot(WS)).research.id

    run = await repo.start_problem_run(WS, research_id)
    failed = await repo.fail_problem_run(run.id, "LLMUnavailable: all routes failed")

    assert failed.status == ProblemRunStatus.FAILED
    assert failed.error == "LLMUnavailable: all routes failed"
    assert [o.title for o in await repo.list_problem_candidates(WS)] == ["Kept one", "Kept two"]


async def test_options_are_isolated_per_project(repo):
    await project_with_options(repo, "ws-a", titles=("A1", "A2"))
    await project_with_options(repo, "ws-b", titles=("B1", "B2", "B3"))

    assert [o.title for o in await repo.list_problem_candidates("ws-a")] == ["A1", "A2"]
    assert [o.title for o in await repo.list_problem_candidates("ws-b")] == ["B1", "B2", "B3"]


async def test_evidence_cannot_be_replaced_after_options_exist(repo):
    """Options cite the evidence, so a new research run must not swap it out underneath them."""
    await project_with_options(repo)
    research = await repo.start_research_run(WS, provider="mock")

    with pytest.raises(ValueError, match="problem options"):
        await repo.complete_research_run(research.id, [make_source(9)])

    assert len(await repo.list_evidence(WS)) == 3


# ── Selecting a problem (mandatory HITL decision) ─────────────────────────────

async def test_select_problem(repo):
    options = await project_with_options(repo)
    chosen = options[1]

    selected = await repo.select_problem(WS, chosen.id)

    assert selected.id == chosen.id
    assert selected.status == ProblemStatus.SELECTED
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.PROBLEM_SELECTED
    assert snapshot.selected_problem.id == chosen.id
    assert snapshot.selected_problem.evidence   # sources come with it

    # The other options are kept as candidates, not deleted.
    statuses = {o.id: o.status for o in await repo.list_problem_candidates(WS)}
    assert statuses == {
        o.id: ProblemStatus.SELECTED if o.id == chosen.id else ProblemStatus.CANDIDATE
        for o in options
    }


async def test_cannot_select_before_options_exist(repo):
    await researched_project(repo)
    with pytest.raises(ProblemSelectionError):
        await repo.select_problem(WS, "anything")


async def test_cannot_select_an_unknown_problem(repo):
    await project_with_options(repo)
    with pytest.raises(ProblemSelectionError):
        await repo.select_problem(WS, "invented-id")
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.PROBLEM_OPTIONS


async def test_cannot_select_another_projects_problem(repo):
    other_options = await project_with_options(repo, "ws-other")
    await project_with_options(repo, WS)

    with pytest.raises(ProblemSelectionError):
        await repo.select_problem(WS, other_options[0].id)


async def test_cannot_select_twice(repo):
    options = await project_with_options(repo)
    await repo.select_problem(WS, options[0].id)

    with pytest.raises(ProblemSelectionError):
        await repo.select_problem(WS, options[1].id)


async def test_select_problem_unknown_project(repo):
    with pytest.raises(ValueError):
        await repo.select_problem("does-not-exist", "anything")


async def test_options_cannot_be_replaced_after_selection(repo):
    options = await project_with_options(repo)
    await repo.select_problem(WS, options[0].id)
    research_id = (await repo.get_snapshot(WS)).research.id
    run = await repo.start_problem_run(WS, research_id)

    with pytest.raises(ValueError, match="already been selected"):
        await complete_with(repo, run.id, [make_candidate([options[0].evidence[0].evidence_source_id])])


async def test_release_01_and_02_data_untouched_by_problems(repo):
    options = await project_with_options(repo)
    await repo.select_problem(WS, options[0].id)

    snapshot = await repo.get_snapshot(WS)
    assert (snapshot.industry, snapshot.branch) == ("Defense", "Navy")
    assert snapshot.research.status == "complete"
    assert len(await repo.list_evidence(WS)) == 3


async def test_database_has_the_new_tables(session):
    tables = await session.run_sync(lambda s: inspect(s.connection()).get_table_names())
    assert {"problem_run", "problem_candidate", "problem_evidence"} <= set(tables)
