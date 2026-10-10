"""
Tests for the AI Strategy workflow (Release 0.7, Step 3).

Covers:
  - the graph running plan_ai_strategy (a skill via the registry) and pausing
    at strategy_review (mandatory HITL)
  - the event sequence and what is saved in the Project Brain
  - re-checks with a preference, their limits, and failed re-checks
  - approval, which ends Release 0.7 at AI_STRATEGY_APPROVED
  - safe failures, retries, and recovery after a restart

Everything is real (graphs, skills, gateway, repository) except the language
model, which is FakeLLMProvider, and an in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.brain.models import Base
from app.core.brain.repository import AIStrategyRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_AI_STRATEGY_RECHECKS,
    AINecessity,
    AIStrategyPreference,
    AIStrategyRunStatus,
    AIStrategyStatus,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.ai_strategy import (
    AIStrategyNotAllowedError,
    approve_strategy,
    build_ai_strategy_graph,
    start_ai_recheck,
    start_ai_strategy,
)
from app.domains.fyp.workflows.ai_strategy import runner as ai_runner
from app.domains.fyp.workflows.ai_strategy.events import FAILED_MESSAGE, RECHECK_FAILED_MESSAGE
from app.domains.fyp.workflows.ai_strategy.runner import INTERRUPTED_ERROR
from app.domains.fyp.workflows.discovery import ProjectNotFoundError, build_discovery_graph
from app.domains.fyp.workflows.discovery import problem_runner, research_runner
from app.domains.fyp.workflows.fyp_design import build_fyp_design_graph
from app.domains.fyp.workflows.fyp_design import runner as fyp_runner
from app.domains.fyp.workflows.project_definition import approve_scope, build_project_definition_graph
from app.domains.fyp.workflows.project_definition import runner as definition_runner
from tests.unit.test_plan_ai_strategy_skill import GOOD_STRATEGY, NO_AI_STRATEGY
from tests.unit.test_project_definition_workflow import defined

WS = "ws-navy"

CHECK_SEQUENCE = [
    EventType.AI_STRATEGY_STARTED,
    EventType.AI_STRATEGY_PROGRESS,      # checking the AI need
    EventType.AI_STRATEGY_PROGRESS,      # checking the answer
    EventType.AI_STRATEGY_PROGRESS,      # saving
    EventType.AI_STRATEGY_READY,
]
ACTIVE_RUNS = (
    research_runner._active_research,
    problem_runner._active_extractions,
    fyp_runner._active_designs,
    definition_runner._active_definitions,
    ai_runner._active_checks,
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
    """All four workflow graphs sharing one registry with real skills and a fake-mode LLM."""
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    return {
        "discovery": build_discovery_graph(MemorySaver(), skills=registry),
        "fyp": build_fyp_design_graph(MemorySaver(), skills=registry),
        "definition": build_project_definition_graph(MemorySaver(), skills=registry),
        "ai": build_ai_strategy_graph(MemorySaver(), skills=registry),
        "fake": gateway.router.provider("fake"),
    }


@pytest.fixture
def graph(setup):
    return setup["ai"]


async def scope_approved(repo, setup, workspace_id=WS):
    """Everything up to an approved scope — as the API does."""
    ready = await defined(repo, setup, workspace_id)
    return await approve_scope(workspace_id, ready.data["definition"]["definition"]["id"], repo, setup["definition"])


async def check(repo, graph, workspace_id=WS):
    session = await start_ai_strategy(workspace_id, repo, graph)
    return session, [event async for event in session.events()]


async def recheck(repo, graph, preference=AIStrategyPreference.WITHOUT_AI, workspace_id=WS):
    session = await start_ai_recheck(workspace_id, preference, repo, graph)
    return session, [event async for event in session.events()]


async def checked(repo, setup, first_answer=GOOD_STRATEGY, workspace_id=WS):
    """A project with a draft AI strategy. The first answer is scripted, so the verdict is known."""
    await scope_approved(repo, setup, workspace_id)
    setup["fake"].script("fake-model", [first_answer])
    _, events = await check(repo, setup["ai"], workspace_id)
    return events[-1]


def strategy_of(event) -> dict:
    return event.data["ai_strategy"]["strategy"]["strategy"]


# ── Scope approval leads here ─────────────────────────────────────────────────

async def test_approving_the_scope_allows_the_ai_check(repo, setup):
    event = await scope_approved(repo, setup)
    assert event.allowed_actions == [AllowedAction.CHECK_AI_NEED]


# ── The first check ───────────────────────────────────────────────────────────

async def test_the_check_streams_events_and_pauses_for_review(repo, setup, graph):
    await scope_approved(repo, setup)

    session, events = await check(repo, graph)

    assert [e.type for e in events] == CHECK_SEQUENCE
    assert events[0].stage == WorkflowState.SCOPE_APPROVED.value
    ready = events[-1]
    assert ready.stage == WorkflowState.AI_STRATEGY.value
    assert ready.status == EventStatus.AWAITING_USER
    assert AllowedAction.APPROVE_AI_STRATEGY in ready.allowed_actions
    view = ready.data["ai_strategy"]
    assert view["core_features"]                                   # the approved core scope
    assert view["strategy"]["strategy"]["necessity"] in {n.value for n in AINecessity}
    assert view["rechecks_left"] == MAX_AI_STRATEGY_RECHECKS
    assert ready.brain_patch["ai_strategy_id"] == view["strategy"]["id"]
    assert ready.brain_patch["ai_necessity"] == view["strategy"]["strategy"]["necessity"]
    assert ready.data["steps"][-1]["state"] == "done"
    assert session.run.status == AIStrategyRunStatus.COMPLETE

    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("strategy_review",)                      # paused for the student
    assert state.values["strategy_id"] == (await repo.get_ai_strategy(WS)).id


async def test_progress_events_never_carry_model_details(repo, setup, graph):
    await scope_approved(repo, setup)
    _, events = await check(repo, graph)
    for event in events[:-1]:
        assert set(event.data) == {
            "industry", "branch", "label", "steps", "completed_steps", "total_steps", "recheck",
        }


async def test_ai_rechecks_offered_follow_the_verdict(repo, setup):
    ready = await checked(repo, setup, GOOD_STRATEGY)                 # trains its own model
    assert ready.allowed_actions == [AllowedAction.APPROVE_AI_STRATEGY, AllowedAction.RECHECK_AI_STRATEGY]
    assert ready.data["ai_strategy"]["available_rechecks"] == ["without_ai", "existing_model"]
    assert ready.data["ai_strategy"]["uses_ai"] is True


async def test_a_project_without_ai_offers_no_rechecks(repo, setup):
    ready = await checked(repo, setup, NO_AI_STRATEGY)
    assert ready.allowed_actions == [AllowedAction.APPROVE_AI_STRATEGY]
    assert ready.data["ai_strategy"]["available_rechecks"] == []
    assert ready.data["ai_strategy"]["uses_ai"] is False


async def test_the_check_needs_an_approved_scope(repo, setup, graph):
    await defined(repo, setup)
    with pytest.raises(AIStrategyNotAllowedError):
        await start_ai_strategy(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_ai_strategy("nope", repo, graph)


async def test_the_first_check_happens_once(repo, setup, graph):
    await checked(repo, setup)
    with pytest.raises(AIStrategyNotAllowedError):
        await start_ai_strategy(WS, repo, graph)


async def test_only_one_check_at_a_time(repo, setup, graph):
    await scope_approved(repo, setup)
    await start_ai_strategy(WS, repo, graph)                       # started, not run yet
    with pytest.raises(AIStrategyRunAlreadyRunningError):
        await start_ai_strategy(WS, repo, graph)


async def test_a_failure_is_safe_and_can_be_retried(repo, setup, graph):
    await scope_approved(repo, setup)
    setup["fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])

    session, events = await check(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.AI_STRATEGY_FAILED
    assert failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.CHECK_AI_NEED]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    assert "internal detail" in session.run.error                  # stored, never sent
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.SCOPE_APPROVED

    _, retry = await check(repo, graph)
    assert retry[-1].type == EventType.AI_STRATEGY_READY


async def test_a_run_left_running_by_a_stopped_server_is_replaced(repo, setup, graph):
    await scope_approved(repo, setup)
    left = await repo.start_ai_strategy_run(WS)                    # "running", but nobody runs it

    _, events = await check(repo, graph)

    assert events[-1].type == EventType.AI_STRATEGY_READY
    assert (await repo._require_ai_run_record(left.id)).error == INTERRUPTED_ERROR


# ── Re-checks ─────────────────────────────────────────────────────────────────

async def test_a_recheck_follows_the_preference_and_uses_one_up(repo, setup, graph):
    await checked(repo, setup)
    first_id = (await repo.get_ai_strategy(WS)).id

    _, events = await recheck(repo, graph, AIStrategyPreference.WITHOUT_AI)

    assert [e.type for e in events] == CHECK_SEQUENCE
    assert events[0].stage == WorkflowState.AI_STRATEGY.value
    assert events[0].data["recheck"] is True
    assert events[1].data["label"] == "Checking again with your preference"
    ready = events[-1]
    assert strategy_of(ready)["necessity"] == "rule_based"         # the fake follows the preference
    assert ready.data["ai_strategy"]["rechecks_left"] == MAX_AI_STRATEGY_RECHECKS - 1
    assert ready.allowed_actions == [AllowedAction.APPROVE_AI_STRATEGY]   # no AI → nothing left to ask
    saved = await repo.get_ai_strategy(WS)
    assert (saved.id, saved.rechecks_used, saved.preference) == (first_id, 1, AIStrategyPreference.WITHOUT_AI)

    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("strategy_review",)
    assert state.values["rechecks_used"] == 1


async def test_the_model_sees_the_previous_answer_in_a_recheck(repo, setup, graph):
    await checked(repo, setup)
    await recheck(repo, graph, AIStrategyPreference.EXISTING_MODEL)
    sent = setup["fake"].calls[-1].input_json
    assert "ready-made model" in sent and "previous_answer" in sent


async def test_rechecks_are_limited(repo, setup, graph):
    await checked(repo, setup)
    setup["fake"].script("fake-model", [GOOD_STRATEGY, GOOD_STRATEGY])     # Grey keeps its verdict
    for _ in range(MAX_AI_STRATEGY_RECHECKS):
        _, events = await recheck(repo, graph, AIStrategyPreference.EXISTING_MODEL)
        assert events[-1].type == EventType.AI_STRATEGY_READY

    assert events[-1].allowed_actions == [AllowedAction.APPROVE_AI_STRATEGY]
    with pytest.raises(AIStrategyNotAllowedError, match="re-checks have been used"):
        await start_ai_recheck(WS, AIStrategyPreference.WITHOUT_AI, repo, graph)


async def test_a_recheck_that_makes_no_sense_is_refused(repo, setup, graph):
    await checked(repo, setup, NO_AI_STRATEGY)
    with pytest.raises(AIStrategyNotAllowedError, match="already works without AI"):
        await start_ai_recheck(WS, AIStrategyPreference.WITHOUT_AI, repo, graph)


async def test_a_failed_recheck_keeps_the_strategy_and_the_review(repo, setup, graph):
    ready = await checked(repo, setup)
    setup["fake"].script("fake-model", [LLMUnavailable("down")])

    _, events = await recheck(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.AI_STRATEGY_FAILED
    assert failed.status == EventStatus.AWAITING_USER                # still reviewing
    assert failed.stage == WorkflowState.AI_STRATEGY.value
    assert failed.data["message"] == RECHECK_FAILED_MESSAGE
    assert strategy_of(failed) == strategy_of(ready)                  # unchanged
    assert failed.data["ai_strategy"]["rechecks_left"] == MAX_AI_STRATEGY_RECHECKS
    assert AllowedAction.RECHECK_AI_STRATEGY in failed.allowed_actions

    _, again = await recheck(repo, graph)                             # the workflow is rebuilt
    assert again[-1].type == EventType.AI_STRATEGY_READY


async def test_rechecks_work_after_a_restart(repo, setup, graph):
    await checked(repo, setup)
    # The paused workflow is lost; the new graph gets fresh skills with a fake-mode LLM.
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None)))
    restarted = build_ai_strategy_graph(MemorySaver(), skills=registry)

    _, events = await recheck(repo, restarted, AIStrategyPreference.WITHOUT_AI)

    assert events[-1].type == EventType.AI_STRATEGY_READY
    assert (await repo.get_ai_strategy(WS)).rechecks_used == 1


# ── Approval ──────────────────────────────────────────────────────────────────

async def test_approving_ends_release_0_7(repo, setup, graph):
    ready = await checked(repo, setup)
    strategy_id = ready.data["ai_strategy"]["strategy"]["id"]

    event = await approve_strategy(WS, strategy_id, repo, graph)

    assert event.type == EventType.AI_STRATEGY_APPROVED
    assert event.stage == WorkflowState.AI_STRATEGY_APPROVED.value
    assert event.status == EventStatus.COMPLETE
    assert event.allowed_actions == [AllowedAction.FIND_DATASETS]   # Release 0.8: datasets come next
    assert event.data["ai_strategy"]["strategy"]["status"] == "approved"
    assert event.data["ai_strategy"]["available_rechecks"] == []

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.AI_STRATEGY_APPROVED
    assert snapshot.ai_strategy.status == AIStrategyStatus.APPROVED
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ()                                           # the workflow has ended


async def test_approval_checks_the_strategy_id(repo, setup, graph):
    await checked(repo, setup)
    with pytest.raises(AIStrategyNotAllowedError):
        await approve_strategy(WS, "someone-elses", repo, graph)


async def test_nothing_changes_after_approval(repo, setup, graph):
    ready = await checked(repo, setup)
    strategy_id = ready.data["ai_strategy"]["strategy"]["id"]
    await approve_strategy(WS, strategy_id, repo, graph)

    with pytest.raises(AIStrategyNotAllowedError):
        await start_ai_recheck(WS, AIStrategyPreference.WITHOUT_AI, repo, graph)
    with pytest.raises(AIStrategyNotAllowedError):
        await approve_strategy(WS, strategy_id, repo, graph)


async def test_approval_works_after_a_restart(repo, setup, graph):
    ready = await checked(repo, setup)
    restarted = build_ai_strategy_graph(MemorySaver(), skills=None)
    calls_before = len(setup["fake"].calls)

    event = await approve_strategy(WS, ready.data["ai_strategy"]["strategy"]["id"], repo, restarted)

    assert event.type == EventType.AI_STRATEGY_APPROVED
    assert len(setup["fake"].calls) == calls_before                   # rebuilt from the Brain, no model call
