"""
Tests for the Technical Plan workflow (Release 0.11, Step 3).
Real graphs, skills, repository and mock search; fake LLM; in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import ArchitectureRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_ARCHITECTURE_REDESIGNS,
    ArchitecturePreference,
    TechnicalPlanStatus,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.technical_plan import (
    ArchitectureNotAllowedError,
    approve_technical_plan,
    build_technical_plan_graph,
    start_architecture_redesign,
    start_technical_plan,
)
from app.domains.fyp.workflows.technical_plan import runner as architecture_runner
from app.domains.fyp.workflows.technical_plan.events import FAILED_MESSAGE, REDESIGN_FAILED_MESSAGE
from app.domains.fyp.workflows.technology_plan import approve_technology
from tests.unit.test_ai_strategy_workflow import repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_technology_workflow import _technology_graph, models_approved, no_leftover_active_runs, plan  # noqa: F401

WS = "ws-navy"
SEQUENCE = [
    EventType.ARCHITECTURE_STARTED,
    EventType.ARCHITECTURE_PROGRESS,
    EventType.ARCHITECTURE_PROGRESS,
    EventType.ARCHITECTURE_PROGRESS,
    EventType.ARCHITECTURE_READY,
]


def _architecture_graph(setup: dict):
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["architecture_fake"] = gateway.router.provider("fake")
    return build_technical_plan_graph(MemorySaver(), skills=registry)


@pytest.fixture(autouse=True)
def no_leftover_designs():
    architecture_runner._active_designs.clear()
    yield
    architecture_runner._active_designs.clear()


@pytest.fixture
def graph(setup):  # noqa: F811
    return _architecture_graph(setup)


async def technology_approved(repo, setup):  # noqa: F811
    await models_approved(repo, setup)
    technology = _technology_graph(setup)
    _, events = await plan(repo, technology)
    return await approve_technology(WS, events[-1].data["technology"]["plan"]["id"], repo, technology)


async def design(repo, graph):  # noqa: F811
    session = await start_technical_plan(WS, repo, graph)
    return session, [event async for event in session.events()]


async def redesign(repo, graph):  # noqa: F811
    session = await start_architecture_redesign(WS, ArchitecturePreference.SIMPLER, repo, graph)
    return session, [event async for event in session.events()]


async def designed(repo, setup, graph):  # noqa: F811
    await technology_approved(repo, setup)
    _, events = await design(repo, graph)
    return events[-1]


def plan_of(event) -> dict:
    return event.data["technical_plan"]["plan"]["plan"]


async def test_approving_the_technology_allows_the_architecture(repo, setup):  # noqa: F811
    event = await technology_approved(repo, setup)
    assert event.allowed_actions == [AllowedAction.DESIGN_ARCHITECTURE]


async def test_designing_streams_events_and_pauses_for_review(repo, setup, graph):  # noqa: F811
    await technology_approved(repo, setup)
    _, events = await design(repo, graph)
    assert [e.type for e in events] == SEQUENCE
    assert events[0].stage == WorkflowState.TECHNOLOGY_APPROVED.value
    ready = events[-1]
    assert ready.stage == WorkflowState.ARCHITECTURE.value and ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.APPROVE_TECHNICAL_PLAN, AllowedAction.REDESIGN_ARCHITECTURE]
    kinds = [c["kind"] for c in plan_of(ready)["architecture"]["components"]]
    assert "model" in kinds and "user" in kinds and "interface" in kinds
    assert plan_of(ready)["evaluation"]["metrics"]
    assert ready.brain_patch["architecture_component_count"] == len(kinds)
    assert (await graph.aget_state({"configurable": {"thread_id": WS}})).next == ("architecture_review",)
    for event in events[:-1]:
        assert set(event.data) == {"industry", "branch", "label", "steps", "completed_steps", "total_steps", "redesign"}


async def test_designing_needs_an_approved_technology_plan(repo, setup, graph):  # noqa: F811
    await models_approved(repo, setup)
    with pytest.raises(ArchitectureNotAllowedError):
        await start_technical_plan(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_technical_plan("nope", repo, graph)


async def test_one_design_at_a_time(repo, setup, graph):  # noqa: F811
    await technology_approved(repo, setup)
    await start_technical_plan(WS, repo, graph)
    with pytest.raises(ArchitectureRunAlreadyRunningError):
        await start_technical_plan(WS, repo, graph)


async def test_a_failure_is_safe_and_can_be_retried(repo, setup, graph):  # noqa: F811
    await technology_approved(repo, setup)
    setup["architecture_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    _, events = await design(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.ARCHITECTURE_FAILED and failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.DESIGN_ARCHITECTURE] and failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    _, retry = await design(repo, graph)
    assert retry[-1].type == EventType.ARCHITECTURE_READY


async def test_a_redesign_is_simpler_and_limited(repo, setup, graph):  # noqa: F811
    first = await designed(repo, setup, graph)
    setup["architecture_fake"].script("fake-model", [LLMUnavailable("down")])
    _, events = await redesign(repo, graph)
    assert events[-1].status == EventStatus.AWAITING_USER and events[-1].data["message"] == REDESIGN_FAILED_MESSAGE
    _, events = await redesign(repo, graph)
    ready = events[-1]
    assert len(plan_of(ready)["architecture"]["components"]) < len(plan_of(first)["architecture"]["components"])
    assert ready.data["technical_plan"]["redesigns_left"] == MAX_ARCHITECTURE_REDESIGNS - 1
    _, events = await redesign(repo, _architecture_graph({}))          # also after a restart
    assert events[-1].allowed_actions == [AllowedAction.APPROVE_TECHNICAL_PLAN]
    with pytest.raises(ArchitectureNotAllowedError, match="redesigns have been used"):
        await start_architecture_redesign(WS, ArchitecturePreference.SIMPLER, repo, graph)


async def test_approving_ends_release_0_11(repo, setup, graph):  # noqa: F811
    ready = await designed(repo, setup, graph)
    plan_id = ready.data["technical_plan"]["plan"]["id"]
    with pytest.raises(ArchitectureNotAllowedError):
        await approve_technical_plan(WS, "someone-elses", repo, graph)
    event = await approve_technical_plan(WS, plan_id, repo, _architecture_graph({}))   # after a restart
    assert event.type == EventType.TECHNICAL_PLAN_APPROVED
    assert event.stage == WorkflowState.TECHNICAL_PLAN_APPROVED.value and event.status == EventStatus.COMPLETE
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.TECHNICAL_PLAN_APPROVED
    assert snapshot.technical_plan.status == TechnicalPlanStatus.APPROVED
    with pytest.raises(ArchitectureNotAllowedError):
        await start_architecture_redesign(WS, ArchitecturePreference.SIMPLER, repo, graph)
