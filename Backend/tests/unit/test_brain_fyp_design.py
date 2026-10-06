"""
Tests for FYP design storage in the Project Brain (Release 0.5, Step 1).

Covers the functional area, design runs, design versions (draft → superseded
→ approved), the redesign limit, approval, and that each step only works at
the right stage.

Uses an in-memory SQLite database so no files are created on disk.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.brain.models import Base, FYPDesignRunRecord
from app.core.brain.repository import (
    FYPDesignError,
    FYPDesignRunAlreadyRunningError,
    WorkspaceBrainRepository,
)
from app.core.brain.schemas import (
    MAX_FYP_ADJUSTMENTS,
    FunctionalArea,
    FYPAdjustment,
    FYPDesign,
    FYPDesignRunKind,
    FYPDesignRunStatus,
    FYPDesignStatus,
    WorkflowState,
)
from tests.unit.test_brain_problems import project_with_options

WS = "ws-navy"

AREA = FunctionalArea(
    functional_area="Maritime Surveillance",
    specific_area="Vessel Behavior Monitoring",
    explanation="The problem is about watching how ships move.",
)
LLM = dict(provider="fake", model="fake-model", prompt_version="v1")


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> WorkspaceBrainRepository:
    return WorkspaceBrainRepository(session)


def make_design(**overrides) -> FYPDesign:
    fields = dict(
        title="Vessel anomaly alerts from public tracking data",
        summary="A web tool that flags unusual vessel movements and explains each alert.",
        target_user="Coastal monitoring analysts",
        system_input="Vessel position reports over time",
        system_output="A ranked list of unusual tracks with a short reason for each",
        main_contribution="Explainable alerts that an analyst can check quickly",
        scope_reduction="Instead of a full surveillance system, one student builds the alerting part.",
    )
    fields.update(overrides)
    return FYPDesign(**fields)


async def chosen_problem(repo, workspace_id: str = WS) -> str:
    """A project where the student has chosen a problem. Returns the problem id."""
    options = await project_with_options(repo, workspace_id)
    await repo.select_problem(workspace_id, options[0].id)
    return options[0].id


async def designed(repo, workspace_id: str = WS) -> str:
    """A project with a saved area and a first design (stage FYP_DESIGN). Returns the design id."""
    await chosen_problem(repo, workspace_id)
    run = await repo.start_fyp_design_run(workspace_id, FYPDesignRunKind.INITIAL)
    await repo.save_functional_area(run.id, AREA, **LLM)
    design = await repo.complete_fyp_design_run(run.id, make_design(), **LLM)
    return design.id


async def redesign(repo, adjustment=FYPAdjustment.MAKE_SIMPLER, note=None, workspace_id: str = WS, **design_fields):
    run = await repo.start_fyp_design_run(workspace_id, FYPDesignRunKind.ADJUSTMENT, adjustment, note)
    return await repo.complete_fyp_design_run(run.id, make_design(**design_fields), **LLM)


# ── Tables and schemas ────────────────────────────────────────────────────────

async def test_new_tables_exist(session):
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"functional_area", "fyp_design_run", "fyp_design"} <= set(names)


@pytest.mark.parametrize(
    "field", ["title", "summary", "target_user", "system_input", "system_output",
              "main_contribution", "scope_reduction"],
)
def test_fyp_design_rejects_empty_text(field):
    with pytest.raises(ValidationError):
        make_design(**{field: ""})


def test_approved_fyp_is_a_workflow_stage():
    assert WorkflowState.APPROVED_FYP.value == "APPROVED_FYP"


# ── Happy path ────────────────────────────────────────────────────────────────

async def test_new_project_snapshot_has_no_fyp_yet(repo):
    snapshot = await repo.create_workspace(WS)
    assert snapshot.functional_area is None
    assert snapshot.fyp_design is None
    assert snapshot.fyp_adjustments_used == 0
    assert snapshot.fyp_design_run is None


async def test_area_then_design_move_the_project_through_the_stages(repo):
    problem_id = await chosen_problem(repo)
    run = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    assert run.status == FYPDesignRunStatus.RUNNING
    assert run.problem_id == problem_id

    area = await repo.save_functional_area(run.id, AREA, **LLM)
    assert area.functional_area == "Maritime Surveillance"
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.AREA_CLASSIFICATION

    design = await repo.complete_fyp_design_run(run.id, make_design(), design_id="d-1", **LLM)
    snapshot = await repo.get_snapshot(WS)
    assert design.id == "d-1"
    assert (design.version, design.status, design.adjustment) == (1, FYPDesignStatus.DRAFT, None)
    assert snapshot.workflow_state == WorkflowState.FYP_DESIGN
    assert snapshot.functional_area.specific_area == "Vessel Behavior Monitoring"
    assert snapshot.fyp_design.id == "d-1"
    assert snapshot.fyp_design_run.status == FYPDesignRunStatus.COMPLETE
    assert (snapshot.fyp_design_run.provider, snapshot.fyp_design_run.model) == ("fake", "fake-model")


async def test_approving_the_draft_ends_at_approved_fyp(repo):
    design_id = await designed(repo)

    approved = await repo.approve_fyp_design(WS, design_id)

    snapshot = await repo.get_snapshot(WS)
    assert approved.status == FYPDesignStatus.APPROVED
    assert approved.approved_at is not None
    assert snapshot.workflow_state == WorkflowState.APPROVED_FYP
    assert snapshot.fyp_design.id == design_id


# ── Redesigns ─────────────────────────────────────────────────────────────────

async def test_a_redesign_adds_a_version_and_supersedes_the_draft(repo):
    first_id = await designed(repo)

    second = await redesign(repo, FYPAdjustment.CHANGE_TARGET_USER, note="For hospital staff", title="Second")

    versions = await repo.list_fyp_designs(WS)
    assert [(d.version, d.status) for d in versions] == [
        (1, FYPDesignStatus.SUPERSEDED), (2, FYPDesignStatus.DRAFT),
    ]
    assert versions[0].id == first_id
    assert (second.adjustment, second.note) == (FYPAdjustment.CHANGE_TARGET_USER, "For hospital staff")
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.fyp_design.title == "Second"
    assert snapshot.fyp_adjustments_used == 1
    assert snapshot.workflow_state == WorkflowState.FYP_DESIGN


async def test_only_three_redesigns_are_allowed(repo):
    await designed(repo)
    for n in range(MAX_FYP_ADJUSTMENTS):
        await redesign(repo, title=f"Version {n + 2}")

    with pytest.raises(FYPDesignError, match="redesigns"):
        await repo.start_fyp_design_run(WS, FYPDesignRunKind.ADJUSTMENT, FYPAdjustment.MAKE_SIMPLER)
    assert await repo.count_fyp_adjustments(WS) == MAX_FYP_ADJUSTMENTS


async def test_a_failed_redesign_does_not_use_up_an_adjustment(repo):
    await designed(repo)
    run = await repo.start_fyp_design_run(WS, FYPDesignRunKind.ADJUSTMENT, FYPAdjustment.REDUCE_COMPLEXITY)

    failed = await repo.fail_fyp_design_run(run.id, "LLMUnavailable: down")

    assert failed.status == FYPDesignRunStatus.FAILED
    assert await repo.count_fyp_adjustments(WS) == 0
    assert (await repo.get_current_fyp_design(WS)).version == 1


async def test_only_the_current_draft_can_be_approved(repo):
    first_id = await designed(repo)
    second = await redesign(repo, title="Second")

    with pytest.raises(FYPDesignError, match="current"):
        await repo.approve_fyp_design(WS, first_id)
    await repo.approve_fyp_design(WS, second.id)


async def test_a_redesign_needs_an_adjustment(repo):
    await designed(repo)
    with pytest.raises(FYPDesignError, match="adjustment"):
        await repo.start_fyp_design_run(WS, FYPDesignRunKind.ADJUSTMENT)


# ── Wrong stage ───────────────────────────────────────────────────────────────

async def test_design_cannot_start_before_a_problem_is_chosen(repo):
    await project_with_options(repo)
    with pytest.raises(FYPDesignError, match="problem"):
        await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)


async def test_initial_design_cannot_start_twice_once_a_design_exists(repo):
    await designed(repo)
    with pytest.raises(FYPDesignError, match="already"):
        await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)


async def test_nothing_changes_after_approval(repo):
    design_id = await designed(repo)
    await repo.approve_fyp_design(WS, design_id)

    with pytest.raises(FYPDesignError):
        await repo.start_fyp_design_run(WS, FYPDesignRunKind.ADJUSTMENT, FYPAdjustment.MAKE_SIMPLER)
    with pytest.raises(FYPDesignError):
        await repo.approve_fyp_design(WS, design_id)


async def test_design_cannot_be_saved_before_the_area(repo):
    await chosen_problem(repo)
    run = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    with pytest.raises(ValueError, match="area"):
        await repo.complete_fyp_design_run(run.id, make_design(), **LLM)


async def test_area_is_only_saved_once(repo):
    await chosen_problem(repo)
    run = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    await repo.save_functional_area(run.id, AREA, **LLM)
    with pytest.raises(ValueError, match="stage"):
        await repo.save_functional_area(run.id, AREA, **LLM)


async def test_a_retry_after_a_failed_design_keeps_the_area(repo):
    await chosen_problem(repo)
    run = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    await repo.save_functional_area(run.id, AREA, **LLM)
    await repo.fail_fyp_design_run(run.id, "LLMUnavailable: down")

    retry = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)       # stage AREA_CLASSIFICATION
    design = await repo.complete_fyp_design_run(retry.id, make_design(), **LLM)

    assert design.version == 1
    assert (await repo.get_functional_area(WS)).functional_area == AREA.functional_area


async def test_a_completed_run_cannot_be_completed_again(repo):
    await chosen_problem(repo)
    run = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    await repo.save_functional_area(run.id, AREA, **LLM)
    await repo.complete_fyp_design_run(run.id, make_design(), **LLM)
    with pytest.raises(ValueError, match="not running"):
        await repo.complete_fyp_design_run(run.id, make_design(), **LLM)


# ── Running runs ──────────────────────────────────────────────────────────────

async def test_only_one_design_run_at_a_time(repo):
    await chosen_problem(repo)
    await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    with pytest.raises(FYPDesignRunAlreadyRunningError):
        await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)


async def test_a_stale_running_run_is_replaced(repo, session):
    await chosen_problem(repo)
    old = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)
    record = await session.get(FYPDesignRunRecord, old.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    await session.commit()

    new = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)

    assert new.id != old.id
    assert (await session.get(FYPDesignRunRecord, old.id)).status == FYPDesignRunStatus.FAILED.value
