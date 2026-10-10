"""
Tests for the Technology Plan workflow (Release 0.10, Step 3).
Real graphs, skills, repository and mock search; fake LLM; in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import TechnologyRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_TECHNOLOGY_REPLANS,
    TechnologyPlanStatus,
    TechnologyPreference,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.model_selection import approve_model_plan
from app.domains.fyp.workflows.model_selection import runner as model_runner
from app.domains.fyp.workflows.technology_plan import (
    TechnologyNotAllowedError,
    approve_technology,
    build_technology_graph,
    start_technology_plan,
    start_technology_replan,
)
from app.domains.fyp.workflows.technology_plan import runner as technology_runner
from app.domains.fyp.workflows.technology_plan.events import FAILED_MESSAGE, REPLAN_FAILED_MESSAGE
from tests.unit.test_ai_strategy_workflow import ACTIVE_RUNS, repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_model_workflow import _model_graph, dataset_selected, look

WS = "ws-navy"
PLAN_SEQUENCE = [
    EventType.TECHNOLOGY_PLAN_STARTED,
    EventType.TECHNOLOGY_PLAN_PROGRESS,
    EventType.TECHNOLOGY_PLAN_PROGRESS,
    EventType.TECHNOLOGY_PLAN_PROGRESS,
    EventType.TECHNOLOGY_PLAN_READY,
]


def _technology_graph(setup: dict):
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["technology_fake"] = gateway.router.provider("fake")
    return build_technology_graph(MemorySaver(), skills=registry)


@pytest.fixture(autouse=True)
def no_leftover_active_runs():
    from app.domains.fyp.workflows.dataset_discovery import runner as dataset_runner
    sets = (*ACTIVE_RUNS, dataset_runner._active_searches, model_runner._active_searches,
            technology_runner._active_plans)
    for active in sets:
        active.clear()
    yield
    for active in sets:
        active.clear()


@pytest.fixture
def graph(setup):  # noqa: F811
    return _technology_graph(setup)


async def models_approved(repo, setup):  # noqa: F811
    await dataset_selected(repo, setup)
    models = _model_graph(setup)
    _, events = await look(repo, models)
    return await approve_model_plan(WS, events[-1].data["models"]["plan"]["id"], repo, models)


async def plan(repo, graph):  # noqa: F811
    session = await start_technology_plan(WS, repo, graph)
    return session, [event async for event in session.events()]


async def replan(repo, graph):  # noqa: F811
    session = await start_technology_replan(WS, TechnologyPreference.SIMPLER, repo, graph)
    return session, [event async for event in session.events()]


async def planned(repo, setup, graph):  # noqa: F811
    await models_approved(repo, setup)
    _, events = await plan(repo, graph)
    return events[-1]


def plan_of(event) -> dict:
    return event.data["technology"]["plan"]["plan"]


async def test_approving_the_model_plan_allows_planning(repo, setup):  # noqa: F811
    event = await models_approved(repo, setup)
    assert event.allowed_actions == [AllowedAction.PLAN_TECHNOLOGY]


async def test_planning_streams_events_and_pauses_for_review(repo, setup, graph):  # noqa: F811
    await models_approved(repo, setup)
    _, events = await plan(repo, graph)
    assert [e.type for e in events] == PLAN_SEQUENCE
    assert events[0].stage == WorkflowState.MODELS_APPROVED.value
    ready = events[-1]
    assert ready.stage == WorkflowState.TECHNOLOGY_PLAN.value and ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.APPROVE_TECHNOLOGY, AllowedAction.REPLAN_TECHNOLOGY]
    areas = [c["area"] for c in plan_of(ready)["stack"]]
    assert "ai_ml" in areas and "frontend" in areas
    assert ready.data["technology"]["uses_ai"] is True
    assert ready.brain_patch["technology_plan_id"] == ready.data["technology"]["plan"]["id"]
    assert (await graph.aget_state({"configurable": {"thread_id": WS}})).next == ("technology_review",)
    for event in events[:-1]:
        assert set(event.data) == {"industry", "branch", "label", "steps", "completed_steps", "total_steps", "replan"}


async def test_planning_needs_an_approved_model_plan_and_one_run_at_a_time(repo, setup, graph):  # noqa: F811
    await dataset_selected(repo, setup)
    with pytest.raises(TechnologyNotAllowedError):
        await start_technology_plan(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_technology_plan("nope", repo, graph)


async def test_one_plan_at_a_time(repo, setup, graph):  # noqa: F811
    await models_approved(repo, setup)
    await start_technology_plan(WS, repo, graph)
    with pytest.raises(TechnologyRunAlreadyRunningError):
        await start_technology_plan(WS, repo, graph)


async def test_a_failure_is_safe_and_can_be_retried(repo, setup, graph):  # noqa: F811
    await models_approved(repo, setup)
    setup["technology_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    session, events = await plan(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.TECHNOLOGY_PLAN_FAILED and failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.PLAN_TECHNOLOGY] and failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    _, retry = await plan(repo, graph)
    assert retry[-1].type == EventType.TECHNOLOGY_PLAN_READY


async def test_a_replan_makes_it_simpler_and_uses_one_up(repo, setup, graph):  # noqa: F811
    first = await planned(repo, setup, graph)
    _, events = await replan(repo, graph)
    ready = events[-1]
    assert [e.type for e in events] == PLAN_SEQUENCE and events[1].data["label"] == "Making the plan simpler and cheaper"
    assert len(plan_of(ready)["stack"]) < len(plan_of(first)["stack"])
    assert ready.data["technology"]["replans_left"] == MAX_TECHNOLOGY_REPLANS - 1
    assert "previous_answer" in setup["technology_fake"].calls[-1].input_json


async def test_replans_are_limited_and_failures_keep_the_review(repo, setup, graph):  # noqa: F811
    ready = await planned(repo, setup, graph)
    setup["technology_fake"].script("fake-model", [LLMUnavailable("down")])
    _, events = await replan(repo, graph)
    assert events[-1].status == EventStatus.AWAITING_USER and events[-1].data["message"] == REPLAN_FAILED_MESSAGE
    assert plan_of(events[-1]) == plan_of(ready)
    for _ in range(MAX_TECHNOLOGY_REPLANS):
        _, events = await replan(repo, graph)
    assert events[-1].allowed_actions == [AllowedAction.APPROVE_TECHNOLOGY]
    with pytest.raises(TechnologyNotAllowedError, match="re-plans have been used"):
        await start_technology_replan(WS, TechnologyPreference.SIMPLER, repo, graph)


async def test_replans_work_after_a_restart(repo, setup, graph):  # noqa: F811
    await planned(repo, setup, graph)
    _, events = await replan(repo, _technology_graph({}))
    assert events[-1].type == EventType.TECHNOLOGY_PLAN_READY
    assert (await repo.get_technology_plan(WS)).replans_used == 1


async def test_approving_ends_release_0_10(repo, setup, graph):  # noqa: F811
    ready = await planned(repo, setup, graph)
    plan_id = ready.data["technology"]["plan"]["id"]
    with pytest.raises(TechnologyNotAllowedError):
        await approve_technology(WS, "someone-elses", repo, graph)
    event = await approve_technology(WS, plan_id, repo, _technology_graph({}))      # also after a restart
    assert event.type == EventType.TECHNOLOGY_APPROVED and event.stage == WorkflowState.TECHNOLOGY_APPROVED.value
    assert event.status == EventStatus.COMPLETE
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.TECHNOLOGY_APPROVED
    assert snapshot.technology_plan.status == TechnologyPlanStatus.APPROVED
    with pytest.raises(TechnologyNotAllowedError):
        await start_technology_replan(WS, TechnologyPreference.SIMPLER, repo, graph)
