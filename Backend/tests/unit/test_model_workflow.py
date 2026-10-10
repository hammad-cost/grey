"""
Tests for the Model Selection workflow (Release 0.9, Step 4).

Covers the graph pausing at model_review, the events and what is saved, the
code-built plan for a project without AI, re-searches and their limits, failed
searches, approval (which ends Release 0.9 at MODELS_APPROVED), and restarts.
Real graphs, skills, repository and mock search; fake LLM; in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import ModelRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_MODEL_RESEARCHES,
    DatasetChoice,
    ModelPlanStatus,
    ModelPreference,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.dataset_discovery import select_dataset_option
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.model_selection import (
    ModelNotAllowedError,
    approve_model_plan,
    build_model_graph,
    start_model_research,
    start_model_search,
)
from app.domains.fyp.workflows.model_selection import runner as model_runner
from app.domains.fyp.workflows.model_selection.events import FAILED_MESSAGE, RESEARCH_FAILED_MESSAGE
from app.domains.fyp.workflows.model_selection.runner import INTERRUPTED_ERROR
from tests.unit.test_ai_strategy_workflow import ACTIVE_RUNS, repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_dataset_workflow import _dataset_graph, search, strategy_approved
from tests.unit.test_plan_ai_strategy_skill import NO_AI_STRATEGY

WS = "ws-navy"

SEARCH_SEQUENCE = [
    EventType.MODEL_SEARCH_STARTED,
    EventType.MODEL_SEARCH_PROGRESS,
    EventType.MODEL_SEARCH_PROGRESS,
    EventType.MODEL_SEARCH_PROGRESS,
    EventType.MODEL_SEARCH_PROGRESS,
    EventType.MODELS_READY,
]


def _model_graph(setup: dict):
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["model_fake"] = gateway.router.provider("fake")
    return build_model_graph(MemorySaver(), skills=registry)


@pytest.fixture(autouse=True)
def no_leftover_active_runs():
    from app.domains.fyp.workflows.dataset_discovery import runner as dataset_runner
    sets = (*ACTIVE_RUNS, dataset_runner._active_searches, model_runner._active_searches)
    for active in sets:
        active.clear()
    yield
    for active in sets:
        active.clear()


@pytest.fixture
def graph(setup):  # noqa: F811
    return _model_graph(setup)


async def dataset_selected(repo, setup, first_answer=None):  # noqa: F811
    """Everything up to a selected dataset — as the API does."""
    if first_answer is None:
        await strategy_approved(repo, setup)
    else:
        await strategy_approved(repo, setup, first_answer)
    datasets = _dataset_graph(setup)
    _, events = await search(repo, datasets)
    plan_id = events[-1].data["datasets"]["plan"]["id"]
    return await select_dataset_option(WS, plan_id, DatasetChoice.PRIMARY, repo, datasets)


async def look(repo, graph):  # noqa: F811
    session = await start_model_search(WS, repo, graph)
    return session, [event async for event in session.events()]


async def research(repo, graph):  # noqa: F811
    session = await start_model_research(WS, ModelPreference.OTHER_OPTIONS, repo, graph)
    return session, [event async for event in session.events()]


async def looked(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup)
    _, events = await look(repo, graph)
    return events[-1]


def plan_of(event) -> dict:
    return event.data["models"]["plan"]["plan"]


# ── Dataset selection leads here ──────────────────────────────────────────────

async def test_selecting_a_dataset_allows_the_model_search(repo, setup):  # noqa: F811
    event = await dataset_selected(repo, setup)
    assert event.allowed_actions == [AllowedAction.FIND_MODELS]


# ── The first search ──────────────────────────────────────────────────────────

async def test_the_search_streams_events_and_pauses_for_review(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup)
    session, events = await look(repo, graph)

    assert [e.type for e in events] == SEARCH_SEQUENCE
    assert events[0].stage == WorkflowState.DATASET_SELECTED.value
    ready = events[-1]
    assert ready.stage == WorkflowState.MODEL_SELECTION.value and ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.APPROVE_MODELS, AllowedAction.REQUEST_OTHER_MODELS]
    view = ready.data["models"]
    assert view["ai_task"] == "anomaly_detection" and view["dataset_name"]
    assert plan_of(ready)["needs_model"] is True and len(plan_of(ready)["options"]) == 2
    assert view["searches_used"] == 4 and view["pages_found"] >= 4
    assert ready.brain_patch["model_plan_id"] == view["plan"]["id"]
    assert ready.brain_patch["model_option_count"] == 2
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("model_review",)
    for event in events[:-1]:
        assert set(event.data) == {"industry", "branch", "label", "steps", "completed_steps", "total_steps", "research"}


async def test_a_project_without_ai_gets_no_model_needed(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup, NO_AI_STRATEGY)
    calls_before = len(setup["model_fake"].calls)
    _, events = await look(repo, graph)
    ready = events[-1]
    assert plan_of(ready)["needs_model"] is False and plan_of(ready)["options"] == []
    assert ready.allowed_actions == [AllowedAction.APPROVE_MODELS]           # nothing to search again for
    assert events[1].data["label"] == "Checking your AI strategy"
    assert len(setup["model_fake"].calls) == calls_before                    # no model call


async def test_the_search_needs_a_selected_dataset(repo, setup, graph):  # noqa: F811
    await strategy_approved(repo, setup)
    with pytest.raises(ModelNotAllowedError):
        await start_model_search(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_model_search("nope", repo, graph)


async def test_the_first_search_happens_once_and_one_at_a_time(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup)
    await start_model_search(WS, repo, graph)
    with pytest.raises(ModelRunAlreadyRunningError):
        await start_model_search(WS, repo, graph)


async def test_a_failure_is_safe_and_can_be_retried(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup)
    setup["model_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    session, events = await look(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.MODEL_SEARCH_FAILED and failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.FIND_MODELS]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json() and "internal detail" in session.run.error
    _, retry = await look(repo, graph)
    assert retry[-1].type == EventType.MODELS_READY


async def test_a_run_left_running_is_replaced(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup)
    left = await repo.start_model_run(WS)
    _, events = await look(repo, graph)
    assert events[-1].type == EventType.MODELS_READY
    assert (await repo._require_model_run_record(left.id)).error == INTERRUPTED_ERROR


# ── Re-searches ───────────────────────────────────────────────────────────────

async def test_other_models_never_repeats_and_uses_one_up(repo, setup, graph):  # noqa: F811
    first = await looked(repo, setup, graph)
    shown = {o["url"] for o in plan_of(first)["options"]}
    _, events = await research(repo, graph)
    ready = events[-1]
    assert [e.type for e in events] == SEARCH_SEQUENCE and events[0].data["research"] is True
    assert not {o["url"] for o in plan_of(ready)["options"]} & shown
    assert ready.data["models"]["researches_left"] == MAX_MODEL_RESEARCHES - 1
    assert "previous_answer" in setup["model_fake"].calls[-1].input_json


async def test_researches_are_limited(repo, setup, graph):  # noqa: F811
    await looked(repo, setup, graph)
    for _ in range(MAX_MODEL_RESEARCHES):
        _, events = await research(repo, graph)
    assert events[-1].allowed_actions == [AllowedAction.APPROVE_MODELS]
    with pytest.raises(ModelNotAllowedError, match="new searches have been used"):
        await start_model_research(WS, ModelPreference.OTHER_OPTIONS, repo, graph)


async def test_a_failed_research_keeps_the_plan_and_the_review(repo, setup, graph):  # noqa: F811
    ready = await looked(repo, setup, graph)
    setup["model_fake"].script("fake-model", [LLMUnavailable("down")])
    _, events = await research(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.MODEL_SEARCH_FAILED and failed.status == EventStatus.AWAITING_USER
    assert failed.data["message"] == RESEARCH_FAILED_MESSAGE
    assert plan_of(failed) == plan_of(ready)
    _, again = await research(repo, graph)
    assert again[-1].type == EventType.MODELS_READY


async def test_researches_work_after_a_restart(repo, setup, graph):  # noqa: F811
    await looked(repo, setup, graph)
    _, events = await research(repo, _model_graph({}))
    assert events[-1].type == EventType.MODELS_READY
    assert (await repo.get_model_plan(WS)).researches_used == 1


# ── Approval ──────────────────────────────────────────────────────────────────

async def test_approving_ends_release_0_9(repo, setup, graph):  # noqa: F811
    ready = await looked(repo, setup, graph)
    plan_id = ready.data["models"]["plan"]["id"]
    with pytest.raises(ModelNotAllowedError):
        await approve_model_plan(WS, "someone-elses", repo, graph)

    event = await approve_model_plan(WS, plan_id, repo, graph)

    assert event.type == EventType.MODELS_APPROVED and event.stage == WorkflowState.MODELS_APPROVED.value
    assert event.status == EventStatus.COMPLETE and event.allowed_actions == [AllowedAction.PLAN_TECHNOLOGY]
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.MODELS_APPROVED
    assert snapshot.model_plan.status == ModelPlanStatus.APPROVED
    assert (await graph.aget_state({"configurable": {"thread_id": WS}})).next == ()
    with pytest.raises(ModelNotAllowedError):
        await start_model_research(WS, ModelPreference.OTHER_OPTIONS, repo, graph)


async def test_approval_works_after_a_restart(repo, setup, graph):  # noqa: F811
    ready = await looked(repo, setup, graph)
    calls_before = len(setup["model_fake"].calls)
    event = await approve_model_plan(WS, ready.data["models"]["plan"]["id"], repo, build_model_graph(MemorySaver()))
    assert event.type == EventType.MODELS_APPROVED
    assert len(setup["model_fake"].calls) == calls_before
