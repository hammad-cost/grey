"""
Tests for the Dataset Discovery workflow (Release 0.8, Step 4).

Covers:
  - the graph running find_datasets (a skill via the registry) and pausing
    at dataset_review (mandatory HITL)
  - the event sequence and what is saved in the Project Brain (including the pages found)
  - re-searches with a preference, their limits, and failed re-searches
  - selecting the primary or the alternative, which ends Release 0.8 at DATASET_SELECTED
  - safe failures (model or search), retries, and recovery after a restart

Everything is real (graphs, skills, gateway, repository, the mock search)
except the language model, which is FakeLLMProvider, and an in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import DatasetRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_DATASET_RESEARCHES,
    DatasetChoice,
    DatasetPlanStatus,
    DatasetPreference,
    DatasetRunStatus,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import SearchUnavailable
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.ai_strategy import approve_strategy
from app.domains.fyp.workflows.dataset_discovery import (
    DatasetNotAllowedError,
    build_dataset_graph,
    select_dataset_option,
    start_dataset_research,
    start_dataset_search,
)
from app.domains.fyp.workflows.dataset_discovery import runner as dataset_runner
from app.domains.fyp.workflows.dataset_discovery.events import FAILED_MESSAGE, RESEARCH_FAILED_MESSAGE
from app.domains.fyp.workflows.dataset_discovery.runner import INTERRUPTED_ERROR
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from tests.unit.test_ai_strategy_workflow import ACTIVE_RUNS, checked, repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_dataset_search import ScriptedSearch
from tests.unit.test_plan_ai_strategy_skill import GOOD_STRATEGY, NO_AI_STRATEGY

WS = "ws-navy"

SEARCH_SEQUENCE = [
    EventType.DATASET_SEARCH_STARTED,
    EventType.DATASET_SEARCH_PROGRESS,     # searching dataset sites
    EventType.DATASET_SEARCH_PROGRESS,     # choosing two options
    EventType.DATASET_SEARCH_PROGRESS,     # checking they fit
    EventType.DATASET_SEARCH_PROGRESS,     # saving
    EventType.DATASET_OPTIONS_READY,
]


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_leftover_active_runs():
    for active in (*ACTIVE_RUNS, dataset_runner._active_searches):
        active.clear()
    yield
    for active in (*ACTIVE_RUNS, dataset_runner._active_searches):
        active.clear()


def _dataset_graph(setup: dict):
    """A dataset graph with its own skills (mock search, fake-mode LLM); its fake LLM goes in setup."""
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["dataset_fake"] = gateway.router.provider("fake")
    return build_dataset_graph(MemorySaver(), skills=registry)


@pytest.fixture
def graph(setup):  # noqa: F811
    return _dataset_graph(setup)


async def strategy_approved(repo, setup, first_answer=GOOD_STRATEGY, workspace_id=WS):  # noqa: F811
    """Everything up to an approved AI strategy — as the API does."""
    ready = await checked(repo, setup, first_answer, workspace_id)
    return await approve_strategy(workspace_id, ready.data["ai_strategy"]["strategy"]["id"], repo, setup["ai"])


async def search(repo, graph, workspace_id=WS):  # noqa: F811
    session = await start_dataset_search(workspace_id, repo, graph)
    return session, [event async for event in session.events()]


async def research(repo, graph, preference=DatasetPreference.OTHER_OPTIONS, workspace_id=WS):  # noqa: F811
    session = await start_dataset_research(workspace_id, preference, repo, graph)
    return session, [event async for event in session.events()]


async def searched(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)
    _, events = await search(repo, graph)
    return events[-1]


def plan_of(event) -> dict:
    return event.data["datasets"]["plan"]["plan"]


# ── AI strategy approval leads here ───────────────────────────────────────────

async def test_approving_the_ai_strategy_allows_the_dataset_search(repo, setup):  # noqa: F811
    event = await strategy_approved(repo, setup)
    assert event.allowed_actions == [AllowedAction.FIND_DATASETS]


# ── The first search ──────────────────────────────────────────────────────────

async def test_the_search_streams_events_and_pauses_for_selection(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)

    session, events = await search(repo, graph)

    assert [e.type for e in events] == SEARCH_SEQUENCE
    assert events[0].stage == WorkflowState.AI_STRATEGY_APPROVED.value
    assert events[1].data["label"] == "Searching dataset sites"
    ready = events[-1]
    assert ready.stage == WorkflowState.DATASET_DISCOVERY.value
    assert ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.SELECT_DATASET, AllowedAction.REQUEST_DATASET_ALTERNATIVE]
    view = ready.data["datasets"]
    assert view["uses_ai"] is True and view["ai_task"] == "anomaly_detection"
    assert view["searches_used"] == 4 and view["pages_found"] == 8
    assert view["researches_left"] == MAX_DATASET_RESEARCHES
    assert view["available_researches"] == ["other_options", "own_data"]
    plan = plan_of(ready)
    assert plan["primary"]["kind"] == plan["alternative"]["kind"] == "public"
    assert plan["primary"]["url"] != plan["alternative"]["url"]
    assert ready.brain_patch["dataset_plan_id"] == view["plan"]["id"]
    assert ready.brain_patch["dataset_status"] == "draft"
    assert session.run.status == DatasetRunStatus.COMPLETE
    assert len(await repo.list_dataset_candidates(session.run.id)) == 8   # the pages are kept

    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("dataset_review",)                        # paused for the student
    assert state.values["plan_id"] == (await repo.get_dataset_plan(WS)).id


async def test_progress_events_never_carry_model_details(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)
    _, events = await search(repo, graph)
    for event in events[:-1]:
        assert set(event.data) == {
            "industry", "branch", "label", "steps", "completed_steps", "total_steps", "research",
        }


async def test_a_project_without_ai_gets_data_to_build_and_test(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup, NO_AI_STRATEGY)
    _, events = await search(repo, graph)
    ready = events[-1]
    assert ready.data["datasets"]["uses_ai"] is False
    assert "doesn't use AI" in plan_of(ready)["purpose"]


async def test_the_search_needs_an_approved_ai_strategy(repo, setup, graph):  # noqa: F811
    await checked(repo, setup)                                     # still a draft
    with pytest.raises(DatasetNotAllowedError):
        await start_dataset_search(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_dataset_search("nope", repo, graph)


async def test_the_first_search_happens_once(repo, setup, graph):  # noqa: F811
    await searched(repo, setup, graph)
    with pytest.raises(DatasetNotAllowedError):
        await start_dataset_search(WS, repo, graph)


async def test_only_one_search_at_a_time(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)
    await start_dataset_search(WS, repo, graph)                     # started, not run yet
    with pytest.raises(DatasetRunAlreadyRunningError):
        await start_dataset_search(WS, repo, graph)


async def test_a_model_failure_is_safe_and_can_be_retried(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)
    setup["dataset_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])

    session, events = await search(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.DATASET_SEARCH_FAILED
    assert failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.FIND_DATASETS]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    assert "internal detail" in session.run.error                  # stored, never sent
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.AI_STRATEGY_APPROVED

    _, retry = await search(repo, graph)
    assert retry[-1].type == EventType.DATASET_OPTIONS_READY


async def test_when_every_search_fails_the_student_can_try_again(repo, setup):  # noqa: F811
    await strategy_approved(repo, setup)
    registry = SkillRegistry()
    register_fyp_skills(registry, ScriptedSearch(error=SearchUnavailable("all down")),
                        build_llm_gateway(Settings(_env_file=None)))
    broken = build_dataset_graph(MemorySaver(), skills=registry)

    session, events = await search(repo, broken)

    assert events[-1].type == EventType.DATASET_SEARCH_FAILED
    assert events[-1].allowed_actions == [AllowedAction.FIND_DATASETS]
    assert "DatasetsUnavailableError" in session.run.error
    assert session.run.searches_used == 4                          # the searches it tried are recorded


async def test_a_run_left_running_by_a_stopped_server_is_replaced(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)
    left = await repo.start_dataset_run(WS)                        # "running", but nobody runs it

    _, events = await search(repo, graph)

    assert events[-1].type == EventType.DATASET_OPTIONS_READY
    assert (await repo._require_dataset_run_record(left.id)).error == INTERRUPTED_ERROR


# ── Re-searches ───────────────────────────────────────────────────────────────

async def test_other_options_finds_different_datasets_and_uses_one_up(repo, setup, graph):  # noqa: F811
    first = await searched(repo, setup, graph)
    shown = {plan_of(first)["primary"]["url"], plan_of(first)["alternative"]["url"]}

    _, events = await research(repo, graph, DatasetPreference.OTHER_OPTIONS)

    assert [e.type for e in events] == SEARCH_SEQUENCE
    assert events[0].stage == WorkflowState.DATASET_DISCOVERY.value
    assert events[0].data["research"] is True
    ready = events[-1]
    new = {plan_of(ready)["primary"]["url"], plan_of(ready)["alternative"]["url"]}
    assert not new & shown                                          # nothing shown before
    assert ready.data["datasets"]["researches_left"] == MAX_DATASET_RESEARCHES - 1
    assert ready.data["datasets"]["searches_used"] == 3
    saved = await repo.get_dataset_plan(WS)
    assert (saved.id, saved.researches_used, saved.preference) == (
        first.data["datasets"]["plan"]["id"], 1, DatasetPreference.OTHER_OPTIONS,
    )
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("dataset_review",)
    assert state.values["researches_used"] == 1


async def test_own_data_becomes_primary_without_new_searches(repo, setup, graph):  # noqa: F811
    first = await searched(repo, setup, graph)

    _, events = await research(repo, graph, DatasetPreference.OWN_DATA)

    ready = events[-1]
    assert events[1].data["label"] == "Looking at the datasets found before"
    assert plan_of(ready)["primary"]["kind"] == "synthetic"
    assert plan_of(ready)["alternative"]["url"] == plan_of(first)["primary"]["url"]   # a page found before
    assert ready.data["datasets"]["searches_used"] == 0
    assert ready.data["datasets"]["available_researches"] == ["other_options"]       # own data is already primary


async def test_the_model_sees_the_request_in_a_research(repo, setup, graph):  # noqa: F811
    await searched(repo, setup, graph)
    await research(repo, graph, DatasetPreference.OWN_DATA)
    sent = setup["dataset_fake"].calls[-1].input_json
    assert "own data" in sent and "previous_answer" in sent


async def test_researches_are_limited(repo, setup, graph):  # noqa: F811
    await searched(repo, setup, graph)
    _, events = await research(repo, graph, DatasetPreference.OTHER_OPTIONS)
    _, events = await research(repo, graph, DatasetPreference.OTHER_OPTIONS)
    assert events[-1].type == EventType.DATASET_OPTIONS_READY
    assert events[-1].allowed_actions == [AllowedAction.SELECT_DATASET]
    with pytest.raises(DatasetNotAllowedError, match="new searches have been used"):
        await start_dataset_research(WS, DatasetPreference.OWN_DATA, repo, graph)


async def test_a_research_that_makes_no_sense_is_refused(repo, setup, graph):  # noqa: F811
    await searched(repo, setup, graph)
    await research(repo, graph, DatasetPreference.OWN_DATA)
    with pytest.raises(DatasetNotAllowedError, match="already data you create"):
        await start_dataset_research(WS, DatasetPreference.OWN_DATA, repo, graph)


async def test_a_failed_research_keeps_the_datasets_and_the_review(repo, setup, graph):  # noqa: F811
    ready = await searched(repo, setup, graph)
    setup["dataset_fake"].script("fake-model", [LLMUnavailable("down")])

    _, events = await research(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.DATASET_SEARCH_FAILED
    assert failed.status == EventStatus.AWAITING_USER               # still reviewing
    assert failed.stage == WorkflowState.DATASET_DISCOVERY.value
    assert failed.data["message"] == RESEARCH_FAILED_MESSAGE
    assert plan_of(failed) == plan_of(ready)                        # unchanged
    assert failed.data["datasets"]["researches_left"] == MAX_DATASET_RESEARCHES
    assert AllowedAction.REQUEST_DATASET_ALTERNATIVE in failed.allowed_actions

    _, again = await research(repo, graph)                          # the workflow is rebuilt
    assert again[-1].type == EventType.DATASET_OPTIONS_READY


async def test_researches_work_after_a_restart(repo, setup, graph):  # noqa: F811
    first = await searched(repo, setup, graph)
    restarted = _dataset_graph({})                                  # the paused workflow is lost

    _, events = await research(repo, restarted, DatasetPreference.OWN_DATA)

    assert events[-1].type == EventType.DATASET_OPTIONS_READY
    # The pages found before come back from the Brain, so own data can still offer one.
    assert plan_of(events[-1])["alternative"]["url"] == plan_of(first)["primary"]["url"]
    assert (await repo.get_dataset_plan(WS)).researches_used == 1


# ── Selection ─────────────────────────────────────────────────────────────────

async def test_selecting_the_alternative_ends_release_0_8(repo, setup, graph):  # noqa: F811
    ready = await searched(repo, setup, graph)
    plan_id = ready.data["datasets"]["plan"]["id"]

    event = await select_dataset_option(WS, plan_id, DatasetChoice.ALTERNATIVE, repo, graph)

    assert event.type == EventType.DATASET_SELECTED
    assert event.stage == WorkflowState.DATASET_SELECTED.value
    assert event.status == EventStatus.COMPLETE
    assert event.allowed_actions == []
    assert event.data["datasets"]["plan"]["selected"] == "alternative"
    assert event.data["datasets"]["available_researches"] == []
    assert event.brain_patch["dataset_selected"] == plan_of(ready)["alternative"]["name"]

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.DATASET_SELECTED
    assert snapshot.dataset_plan.status == DatasetPlanStatus.SELECTED
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ()                                         # the workflow has ended


async def test_selection_checks_the_plan_id(repo, setup, graph):  # noqa: F811
    await searched(repo, setup, graph)
    with pytest.raises(DatasetNotAllowedError):
        await select_dataset_option(WS, "someone-elses", DatasetChoice.PRIMARY, repo, graph)


async def test_nothing_changes_after_selection(repo, setup, graph):  # noqa: F811
    ready = await searched(repo, setup, graph)
    plan_id = ready.data["datasets"]["plan"]["id"]
    await select_dataset_option(WS, plan_id, DatasetChoice.PRIMARY, repo, graph)

    with pytest.raises(DatasetNotAllowedError):
        await start_dataset_research(WS, DatasetPreference.OTHER_OPTIONS, repo, graph)
    with pytest.raises(DatasetNotAllowedError):
        await select_dataset_option(WS, plan_id, DatasetChoice.ALTERNATIVE, repo, graph)


async def test_selection_works_after_a_restart(repo, setup, graph):  # noqa: F811
    ready = await searched(repo, setup, graph)
    restarted = build_dataset_graph(MemorySaver(), skills=None)
    calls_before = len(setup["dataset_fake"].calls)

    event = await select_dataset_option(WS, ready.data["datasets"]["plan"]["id"], DatasetChoice.PRIMARY, repo, restarted)

    assert event.type == EventType.DATASET_SELECTED
    assert len(setup["dataset_fake"].calls) == calls_before         # rebuilt from the Brain, no model call
