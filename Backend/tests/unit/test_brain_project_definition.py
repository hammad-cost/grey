"""
Tests for project definition and scope storage in the Project Brain (Release 0.6, Step 1).

Covers the definition runs, saving the definition with its scope items,
moving items between core / optional / out of scope (and the scope rules),
approval, and that each step only works at the right stage.

Uses an in-memory SQLite database so no files are created on disk.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.brain.models import Base, ProjectDefinitionRunRecord
from app.core.brain.repository import (
    ProjectDefinitionError,
    ProjectDefinitionRunAlreadyRunningError,
    WorkspaceBrainRepository,
)
from app.core.brain.schemas import (
    MAX_CORE_FEATURES,
    MIN_CORE_FEATURES,
    ProblemDefinition,
    ProjectDefinition,
    ProjectDefinitionRunStatus,
    ProjectDefinitionStatus,
    ProposedSolution,
    ScopeItem,
    ScopeKind,
    SolutionModule,
    StoredScopeItem,
    WorkflowState,
)
from app.core.brain.scope_rules import ScopeChangeError, move_scope_item
from tests.unit.test_brain_fyp_design import LLM, designed

WS = "ws-navy"


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


def make_definition(core: int = 3, optional: int = 2, out: int = 2) -> ProjectDefinition:
    scope = (
        [ScopeItem(title=f"Core {i}", description=f"Must-have feature {i}.", kind=ScopeKind.CORE) for i in range(core)]
        + [ScopeItem(title=f"Optional {i}", description="Nice to have.", kind=ScopeKind.OPTIONAL) for i in range(optional)]
        + [ScopeItem(title=f"Out {i}", description="Not in this project.", kind=ScopeKind.OUT_OF_SCOPE) for i in range(out)]
    )
    return ProjectDefinition(
        problem_definition=ProblemDefinition(
            problem_statement="Analysts miss unusual vessel movements.",
            affected_users="Coastal monitoring analysts",
            why_it_matters="Missed movements delay responses.",
            current_solutions="Large commercial monitoring platforms.",
            gap="No simple tool explains each alert.",
            what_will_be_built="A web tool that flags unusual tracks and explains them.",
        ),
        proposed_solution=ProposedSolution(
            system_purpose="Help analysts spot and understand unusual vessel movements.",
            modules=[
                SolutionModule(name="Data upload", purpose="Load position reports."),
                SolutionModule(name="Alert view", purpose="Show unusual tracks with reasons."),
            ],
            workflow_steps=["Upload reports", "Grey's tool checks the tracks", "Analyst reviews alerts"],
        ),
        scope=scope,
    )


async def approved_fyp(repo, workspace_id: str = WS) -> str:
    """A project whose FYP design is approved (stage APPROVED_FYP). Returns the design id."""
    design_id = await designed(repo, workspace_id)
    await repo.approve_fyp_design(workspace_id, design_id)
    return design_id


async def defined(repo, workspace_id: str = WS, **sizes):
    """A project with a saved definition (stage SCOPE). Returns the stored definition."""
    await approved_fyp(repo, workspace_id)
    run = await repo.start_project_definition_run(workspace_id)
    return await repo.complete_project_definition_run(run.id, make_definition(**sizes), **LLM)


def items_of(definition, kind: ScopeKind) -> list[str]:
    return [item.title for item in definition.scope if item.kind == kind]


# ── Tables and schemas ────────────────────────────────────────────────────────

async def test_new_tables_exist(session):
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"project_definition_run", "project_definition", "scope_item"} <= set(names)


def test_proposed_solution_needs_modules_and_steps():
    with pytest.raises(ValidationError):
        ProposedSolution(system_purpose="x", modules=[SolutionModule(name="a", purpose="b")],
                         workflow_steps=["1", "2", "3"])
    with pytest.raises(ValidationError):
        ProposedSolution(system_purpose="x", modules=[SolutionModule(name="a", purpose="b")] * 2,
                         workflow_steps=["1", "2"])


def test_scope_item_title_is_short():
    with pytest.raises(ValidationError):
        ScopeItem(title="x" * 81, description="d", kind=ScopeKind.CORE)


# ── Scope rules (plain code) ──────────────────────────────────────────────────

def stored(kinds: list[ScopeKind]) -> list[StoredScopeItem]:
    positions: dict[ScopeKind, int] = {}
    items = []
    for index, kind in enumerate(kinds):
        positions[kind] = positions.get(kind, -1) + 1
        items.append(StoredScopeItem(id=f"i{index}", title=f"Item {index}", description="d",
                                     kind=kind, position=positions[kind]))
    return items


def test_move_puts_the_item_at_the_end_of_its_new_list():
    items = stored([ScopeKind.CORE] * 3 + [ScopeKind.OPTIONAL])
    moved = move_scope_item(items, "i0", ScopeKind.OPTIONAL)
    assert [(i.id, i.kind) for i in moved] == [
        ("i1", ScopeKind.CORE), ("i2", ScopeKind.CORE), ("i3", ScopeKind.OPTIONAL), ("i0", ScopeKind.OPTIONAL),
    ]
    assert items[0].kind == ScopeKind.CORE          # the input is not changed


def test_core_keeps_a_minimum_number_of_features():
    items = stored([ScopeKind.CORE] * MIN_CORE_FEATURES + [ScopeKind.OPTIONAL])
    with pytest.raises(ScopeChangeError, match="at least"):
        move_scope_item(items, "i0", ScopeKind.OUT_OF_SCOPE)


def test_core_has_a_maximum_number_of_features():
    items = stored([ScopeKind.CORE] * MAX_CORE_FEATURES + [ScopeKind.OPTIONAL])
    with pytest.raises(ScopeChangeError, match="at most"):
        move_scope_item(items, f"i{MAX_CORE_FEATURES}", ScopeKind.CORE)


def test_unknown_items_and_no_op_moves_are_rejected():
    items = stored([ScopeKind.CORE] * 3)
    with pytest.raises(ScopeChangeError):
        move_scope_item(items, "nope", ScopeKind.OPTIONAL)
    with pytest.raises(ScopeChangeError, match="already"):
        move_scope_item(items, "i0", ScopeKind.CORE)


# ── Definition runs ───────────────────────────────────────────────────────────

async def test_definition_needs_an_approved_fyp(repo):
    await designed(repo)                                  # stage FYP_DESIGN, not approved yet
    with pytest.raises(ProjectDefinitionError):
        await repo.start_project_definition_run(WS)


async def test_unknown_project_raises(repo):
    with pytest.raises(ValueError):
        await repo.start_project_definition_run("nope")


async def test_complete_saves_the_definition_and_moves_to_scope(repo):
    design_id = await approved_fyp(repo)
    run = await repo.start_project_definition_run(WS)
    assert run.status == ProjectDefinitionRunStatus.RUNNING
    assert run.design_id == design_id

    saved = await repo.complete_project_definition_run(
        run.id, make_definition(), definition_id="def-1", item_ids=[f"s{i}" for i in range(7)], **LLM,
    )

    assert saved.id == "def-1"
    assert saved.status == ProjectDefinitionStatus.DRAFT
    assert saved.design_id == design_id
    assert items_of(saved, ScopeKind.CORE) == ["Core 0", "Core 1", "Core 2"]
    assert items_of(saved, ScopeKind.OPTIONAL) == ["Optional 0", "Optional 1"]
    assert items_of(saved, ScopeKind.OUT_OF_SCOPE) == ["Out 0", "Out 1"]
    assert [i.id for i in saved.scope][:2] == ["s0", "s1"]
    assert saved.proposed_solution.modules[0].name == "Data upload"

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.SCOPE
    assert snapshot.project_definition.id == "def-1"
    assert snapshot.project_definition_run.status == ProjectDefinitionRunStatus.COMPLETE
    assert snapshot.project_definition_run.provider == "fake"


async def test_item_ids_must_match_the_scope(repo):
    await approved_fyp(repo)
    run = await repo.start_project_definition_run(WS)
    with pytest.raises(ValueError):
        await repo.complete_project_definition_run(run.id, make_definition(), item_ids=["only-one"], **LLM)


async def test_a_project_is_defined_only_once(repo):
    await defined(repo)
    with pytest.raises(ProjectDefinitionError):
        await repo.start_project_definition_run(WS)


async def test_only_one_run_at_a_time(repo):
    await approved_fyp(repo)
    await repo.start_project_definition_run(WS)
    with pytest.raises(ProjectDefinitionRunAlreadyRunningError):
        await repo.start_project_definition_run(WS)


async def test_a_stale_run_does_not_block_forever(repo, session):
    await approved_fyp(repo)
    old = await repo.start_project_definition_run(WS)
    record = await session.get(ProjectDefinitionRunRecord, old.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    await session.commit()

    new = await repo.start_project_definition_run(WS)
    assert new.id != old.id
    assert (await session.get(ProjectDefinitionRunRecord, old.id)).status == "failed"


async def test_a_failed_run_keeps_the_stage_and_can_be_retried(repo):
    await approved_fyp(repo)
    run = await repo.start_project_definition_run(WS)
    failed = await repo.fail_project_definition_run(run.id, "LLMUnavailable: down")
    assert failed.status == ProjectDefinitionRunStatus.FAILED
    assert failed.error == "LLMUnavailable: down"

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.APPROVED_FYP
    assert snapshot.project_definition is None
    assert (await repo.start_project_definition_run(WS)).status == ProjectDefinitionRunStatus.RUNNING


async def test_a_finished_run_cannot_be_completed_again(repo):
    await approved_fyp(repo)
    run = await repo.start_project_definition_run(WS)
    await repo.fail_project_definition_run(run.id, "x")
    with pytest.raises(ValueError):
        await repo.complete_project_definition_run(run.id, make_definition(), **LLM)


# ── Scope changes and approval ────────────────────────────────────────────────

async def test_move_scope_item_saves_the_new_list(repo):
    definition = await defined(repo)
    first_core = definition.scope[0]

    updated = await repo.move_scope_item(WS, first_core.id, ScopeKind.OPTIONAL)

    assert items_of(updated, ScopeKind.CORE) == ["Core 1", "Core 2"]
    assert items_of(updated, ScopeKind.OPTIONAL) == ["Optional 0", "Optional 1", "Core 0"]
    assert updated.scope_changes == 1
    assert (await repo.get_project_definition(WS)).scope == updated.scope


async def test_move_follows_the_scope_rules(repo):
    definition = await defined(repo, core=MIN_CORE_FEATURES)
    with pytest.raises(ScopeChangeError):
        await repo.move_scope_item(WS, definition.scope[0].id, ScopeKind.OUT_OF_SCOPE)
    assert (await repo.get_project_definition(WS)).scope_changes == 0


async def test_scope_cannot_change_before_it_exists(repo):
    await approved_fyp(repo)
    with pytest.raises(ProjectDefinitionError):
        await repo.move_scope_item(WS, "x", ScopeKind.CORE)


async def test_approve_moves_to_scope_approved(repo):
    definition = await defined(repo)

    approved = await repo.approve_project_definition(WS, definition.id)

    assert approved.status == ProjectDefinitionStatus.APPROVED
    assert approved.approved_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.SCOPE_APPROVED


async def test_approve_checks_the_definition_id(repo):
    await defined(repo)
    with pytest.raises(ProjectDefinitionError):
        await repo.approve_project_definition(WS, "someone-elses")


async def test_nothing_changes_after_approval(repo):
    definition = await defined(repo)
    await repo.approve_project_definition(WS, definition.id)

    with pytest.raises(ProjectDefinitionError):
        await repo.move_scope_item(WS, definition.scope[0].id, ScopeKind.OPTIONAL)
    with pytest.raises(ProjectDefinitionError):
        await repo.approve_project_definition(WS, definition.id)


async def test_projects_are_kept_apart(repo):
    await defined(repo, workspace_id="ws-a")
    await approved_fyp(repo, "ws-b")
    assert (await repo.get_project_definition("ws-a")) is not None
    assert (await repo.get_project_definition("ws-b")) is None
