"""
Tests for the Project Definition workflow (Release 0.6, Step 3).

Covers:
  - the graph running define_project (a skill via the registry) and pausing
    at scope_review (mandatory HITL)
  - the event sequence and what is saved in the Project Brain
  - moving features between core / optional / out of scope, and the rules
  - approval, which ends Release 0.6 at SCOPE_APPROVED
  - safe failures, retries, and recovery after a restart

Everything is real (graphs, skills, gateway, repository) except the language
model, which is FakeLLMProvider, and an in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.brain.models import Base
from app.core.brain.repository import ProjectDefinitionRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    ProjectDefinitionRunStatus,
    ProjectDefinitionStatus,
    ScopeKind,
    WorkflowState,
)
from app.core.brain.scope_rules import ScopeChangeError
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import ProjectNotFoundError, build_discovery_graph
from app.domains.fyp.workflows.discovery import problem_runner, research_runner
from app.domains.fyp.workflows.fyp_design import approve_fyp, build_fyp_design_graph
from app.domains.fyp.workflows.fyp_design import runner as fyp_runner
from app.domains.fyp.workflows.project_definition import (
    ProjectDefinitionNotAllowedError,
    approve_scope,
    build_project_definition_graph,
    move_scope,
    start_project_definition,
)
from app.domains.fyp.workflows.project_definition import runner as definition_runner
from app.domains.fyp.workflows.project_definition.events import FAILED_MESSAGE
from app.domains.fyp.workflows.project_definition.runner import INTERRUPTED_ERROR
from tests.unit.test_fyp_design_workflow import chosen, design

WS = "ws-navy"

DEFINITION_SEQUENCE = [
    EventType.PROJECT_DEFINITION_STARTED,
    EventType.PROJECT_DEFINITION_PROGRESS,      # writing
    EventType.PROJECT_DEFINITION_PROGRESS,      # checking
    EventType.PROJECT_DEFINITION_PROGRESS,      # saving
    EventType.PROJECT_DEFINITION_READY,
]
ACTIVE_RUNS = (
    research_runner._active_research,
    problem_runner._active_extractions,
    fyp_runner._active_designs,
    definition_runner._active_definitions,
)


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_leftover_active_runs():
    for active in ACTIVE_RUNS:
        active.clear()
    yield
    for active in ACTIVE_RUNS:
        active.clear()


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield WorkspaceBrainRepository(session)
    await engine.dispose()


@pytest.fixture
def setup():
    """All three workflow graphs sharing one registry with real skills and a fake-mode LLM."""
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    return {
        "discovery": build_discovery_graph(MemorySaver(), skills=registry),
        "fyp": build_fyp_design_graph(MemorySaver(), skills=registry),
        "definition": build_project_definition_graph(MemorySaver(), skills=registry),
        "fake": gateway.router.provider("fake"),
    }


@pytest.fixture
def graph(setup):
    return setup["definition"]


async def approved(repo, setup, workspace_id=WS):
    """Research, choose a problem, design the FYP and approve it — as the API does."""
    await chosen(repo, setup, workspace_id)
    _, events = await design(repo, setup["fyp"], workspace_id)
    return await approve_fyp(workspace_id, events[-1].data["fyp"]["design"]["id"], repo, setup["fyp"])


async def define(repo, graph, workspace_id=WS):
    session = await start_project_definition(workspace_id, repo, graph)
    return session, [event async for event in session.events()]


async def defined(repo, setup, workspace_id=WS):
    await approved(repo, setup, workspace_id)
    _, events = await define(repo, setup["definition"], workspace_id)
    return events[-1]


def scope_of(event, kind: ScopeKind) -> list[dict]:
    return [item for item in event.data["definition"]["definition"]["scope"] if item["kind"] == kind.value]


# ── Approval of the FYP leads here ────────────────────────────────────────────

async def test_approving_the_fyp_allows_defining_the_project(repo, setup):
    event = await approved(repo, setup)
    assert event.allowed_actions == [AllowedAction.DEFINE_PROJECT]


# ── Writing the definition ────────────────────────────────────────────────────

async def test_definition_streams_events_and_pauses_for_review(repo, setup, graph):
    await approved(repo, setup)

    session, events = await define(repo, graph)

    assert [e.type for e in events] == DEFINITION_SEQUENCE
    ready = events[-1]
    assert ready.stage == WorkflowState.SCOPE.value
    assert ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.APPROVE_SCOPE, AllowedAction.MODIFY_SCOPE]
    view = ready.data["definition"]
    assert view["target_user"]                                        # from the approved design
    assert view["definition"]["problem_definition"]["gap"]
    assert len(scope_of(ready, ScopeKind.CORE)) == 3
    assert ready.brain_patch["core_feature_count"] == 3
    assert ready.data["steps"][-1]["state"] == "done"
    assert session.run.status == ProjectDefinitionRunStatus.COMPLETE

    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("scope_review",)                            # paused for the student


async def test_the_brain_and_the_workflow_agree_on_ids(repo, setup, graph):
    await approved(repo, setup)
    await define(repo, graph)

    saved = await repo.get_project_definition(WS)
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.values["definition_id"] == saved.id
    assert [i["id"] for i in state.values["scope"]] == [i.id for i in saved.scope]
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.SCOPE


async def test_progress_events_never_carry_model_details(repo, setup, graph):
    await approved(repo, setup)
    _, events = await define(repo, graph)
    for event in events[:-1]:
        assert set(event.data) == {"industry", "branch", "label", "steps", "completed_steps", "total_steps"}


async def test_definition_needs_an_approved_fyp(repo, setup, graph):
    await chosen(repo, setup)
    with pytest.raises(ProjectDefinitionNotAllowedError):
        await start_project_definition(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_project_definition("nope", repo, graph)


async def test_a_project_is_defined_only_once(repo, setup, graph):
    await defined(repo, setup)
    with pytest.raises(ProjectDefinitionNotAllowedError):
        await start_project_definition(WS, repo, graph)


async def test_only_one_definition_at_a_time(repo, setup, graph):
    await approved(repo, setup)
    await start_project_definition(WS, repo, graph)          # started, not run yet
    with pytest.raises(ProjectDefinitionRunAlreadyRunningError):
        await start_project_definition(WS, repo, graph)


async def test_a_failure_is_safe_and_can_be_retried(repo, setup, graph):
    await approved(repo, setup)
    setup["fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])

    session, events = await define(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.PROJECT_DEFINITION_FAILED
    assert failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.DEFINE_PROJECT]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    assert session.run.status == ProjectDefinitionRunStatus.FAILED
    assert "internal detail" in session.run.error                     # stored, never sent
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.APPROVED_FYP

    _, retry = await define(repo, graph)
    assert retry[-1].type == EventType.PROJECT_DEFINITION_READY


async def test_a_run_left_running_by_a_stopped_server_is_replaced(repo, setup, graph):
    await approved(repo, setup)
    left = await repo.start_project_definition_run(WS)                # "running", but nobody runs it

    _, events = await define(repo, graph)

    assert events[-1].type == EventType.PROJECT_DEFINITION_READY
    runs = await repo.get_latest_project_definition_run(WS)
    assert runs.id != left.id
    snapshot_run = await repo._require_definition_run_record(left.id)
    assert snapshot_run.error == INTERRUPTED_ERROR


# ── Scope changes ─────────────────────────────────────────────────────────────

async def test_moving_a_feature_updates_the_brain_and_the_workflow(repo, setup, graph):
    ready = await defined(repo, setup)
    item = scope_of(ready, ScopeKind.CORE)[0]

    event = await move_scope(WS, item["id"], ScopeKind.OPTIONAL, repo, graph)

    assert event.type == EventType.SCOPE_UPDATED
    assert event.status == EventStatus.AWAITING_USER
    assert event.allowed_actions == [AllowedAction.APPROVE_SCOPE, AllowedAction.MODIFY_SCOPE]
    assert event.data["moved"] == item["title"]
    assert scope_of(event, ScopeKind.OPTIONAL)[-1]["id"] == item["id"]
    assert event.brain_patch["core_feature_count"] == 2

    saved = await repo.get_project_definition(WS)
    assert saved.scope_changes == 1
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("scope_review",)                            # still reviewing
    moved = next(i for i in state.values["scope"] if i["id"] == item["id"])
    assert moved["kind"] == "optional"


async def test_a_move_that_breaks_a_rule_changes_nothing(repo, setup, graph):
    ready = await defined(repo, setup)
    core = scope_of(ready, ScopeKind.CORE)
    await move_scope(WS, core[0]["id"], ScopeKind.OUT_OF_SCOPE, repo, graph)     # 3 → 2 core

    with pytest.raises(ScopeChangeError):
        await move_scope(WS, core[1]["id"], ScopeKind.OUT_OF_SCOPE, repo, graph)  # 2 → 1: not allowed

    assert (await repo.get_project_definition(WS)).scope_changes == 1


async def test_scope_cannot_change_before_the_definition_exists(repo, setup, graph):
    await approved(repo, setup)
    with pytest.raises(ProjectDefinitionNotAllowedError):
        await move_scope(WS, "x", ScopeKind.CORE, repo, graph)


async def test_moves_work_after_a_restart(repo, setup, graph):
    ready = await defined(repo, setup)
    item = scope_of(ready, ScopeKind.OPTIONAL)[0]
    restarted = build_project_definition_graph(MemorySaver(), skills=None)          # the paused workflow is lost
    calls_before = len(setup["fake"].calls)

    event = await move_scope(WS, item["id"], ScopeKind.CORE, repo, restarted)

    assert scope_of(event, ScopeKind.CORE)[-1]["id"] == item["id"]
    assert len(setup["fake"].calls) == calls_before                   # rebuilt from the Brain, no model call


# ── Approval ──────────────────────────────────────────────────────────────────

async def test_approving_the_scope_ends_release_0_6(repo, setup, graph):
    ready = await defined(repo, setup)
    definition_id = ready.data["definition"]["definition"]["id"]

    event = await approve_scope(WS, definition_id, repo, graph)

    assert event.type == EventType.SCOPE_APPROVED
    assert event.stage == WorkflowState.SCOPE_APPROVED.value
    assert event.status == EventStatus.COMPLETE
    assert event.allowed_actions == []
    assert event.data["definition"]["definition"]["status"] == "approved"

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.SCOPE_APPROVED
    assert snapshot.project_definition.status == ProjectDefinitionStatus.APPROVED
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ()                                           # the workflow has ended


async def test_approval_checks_the_definition_id(repo, setup, graph):
    await defined(repo, setup)
    with pytest.raises(ProjectDefinitionNotAllowedError):
        await approve_scope(WS, "someone-elses", repo, graph)


async def test_nothing_changes_after_approval(repo, setup, graph):
    ready = await defined(repo, setup)
    definition = ready.data["definition"]["definition"]
    await approve_scope(WS, definition["id"], repo, graph)

    with pytest.raises(ProjectDefinitionNotAllowedError):
        await move_scope(WS, definition["scope"][0]["id"], ScopeKind.OPTIONAL, repo, graph)
    with pytest.raises(ProjectDefinitionNotAllowedError):
        await approve_scope(WS, definition["id"], repo, graph)


async def test_approval_works_after_a_restart(repo, setup, graph):
    ready = await defined(repo, setup)
    restarted = build_project_definition_graph(MemorySaver(), skills=None)

    event = await approve_scope(WS, ready.data["definition"]["definition"]["id"], repo, restarted)

    assert event.type == EventType.SCOPE_APPROVED
