"""
Tests for the Supervisor Readiness workflow (Release 0.13, Step 3).
Real graphs, skills, repository and mock search; fake LLM; in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import ReadinessRunAlreadyRunningError
from app.core.brain.schemas import SupervisorBriefStatus, WorkflowState
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.feasibility import accept_feasibility_report
from app.domains.fyp.workflows.supervisor_readiness import (
    ReadinessNotAllowedError,
    build_supervisor_readiness_graph,
    confirm_supervisor_ready,
    start_supervisor_brief,
)
from app.domains.fyp.workflows.supervisor_readiness import runner as readiness_runner
from app.domains.fyp.workflows.supervisor_readiness.events import FAILED_MESSAGE
from tests.unit.test_ai_strategy_workflow import repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_feasibility_workflow import _feasibility_graph, assess, technical_plan_approved
from tests.unit.test_technology_workflow import no_leftover_active_runs  # noqa: F401 (fixture)

WS = "ws-navy"
SEQUENCE = [EventType.SUPERVISOR_BRIEF_STARTED] + [EventType.SUPERVISOR_BRIEF_PROGRESS] * 4 + [EventType.SUPERVISOR_READINESS_READY]


def _brief_graph(setup: dict):
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["brief_fake"] = gateway.router.provider("fake")
    return build_supervisor_readiness_graph(MemorySaver(), skills=registry)


@pytest.fixture(autouse=True)
def no_leftover_briefs():
    from app.domains.fyp.workflows.feasibility import runner as feasibility_runner
    for active in (readiness_runner._active_briefs, feasibility_runner._active_assessments):
        active.clear()
    yield
    for active in (readiness_runner._active_briefs, feasibility_runner._active_assessments):
        active.clear()


@pytest.fixture
def graph(setup):  # noqa: F811
    return _brief_graph(setup)


async def feasibility_accepted(repo, setup):  # noqa: F811
    await technical_plan_approved(repo, setup)
    feasibility = _feasibility_graph(setup)
    _, events = await assess(repo, feasibility)
    return await accept_feasibility_report(WS, events[-1].data["feasibility"]["report"]["id"], repo, feasibility)


async def prepare(repo, graph):  # noqa: F811
    session = await start_supervisor_brief(WS, repo, graph)
    return session, [event async for event in session.events()]


async def test_accepting_feasibility_allows_the_brief(repo, setup):  # noqa: F811
    event = await feasibility_accepted(repo, setup)
    assert event.allowed_actions == [AllowedAction.PREPARE_SUPERVISOR_BRIEF]


async def test_the_brief_streams_events_and_pauses_for_confirmation(repo, setup, graph):  # noqa: F811
    await feasibility_accepted(repo, setup)
    _, events = await prepare(repo, graph)
    assert [e.type for e in events] == SEQUENCE
    ready = events[-1]
    assert ready.stage == WorkflowState.SUPERVISOR_READINESS.value and ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.CONFIRM_SUPERVISOR_READY]
    view = ready.data["supervisor_brief"]
    brief = view["brief"]["brief"]
    assert len(brief["checks"]) == 9 and len(brief["questions"]) == 10 and len(brief["summary"]) == 14
    assert view["ready"] in (True, False) and ready.brain_patch["supervisor_attention_count"] == view["attention_count"]
    assert (await graph.aget_state({"configurable": {"thread_id": WS}})).next == ("readiness_review",)
    for event in events[:-1]:
        assert set(event.data) == {"industry", "branch", "label", "steps", "completed_steps", "total_steps"}


async def test_the_brief_needs_accepted_feasibility_and_runs_once(repo, setup, graph):  # noqa: F811
    await technical_plan_approved(repo, setup)
    with pytest.raises(ReadinessNotAllowedError):
        await start_supervisor_brief(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_supervisor_brief("nope", repo, graph)


async def test_one_brief_at_a_time_and_failures_are_safe(repo, setup, graph):  # noqa: F811
    await feasibility_accepted(repo, setup)
    await start_supervisor_brief(WS, repo, graph)
    with pytest.raises(ReadinessRunAlreadyRunningError):
        await start_supervisor_brief(WS, repo, graph)
    readiness_runner._active_briefs.clear()
    setup["brief_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    _, events = await prepare(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.SUPERVISOR_BRIEF_FAILED and failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.PREPARE_SUPERVISOR_BRIEF] and failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    _, retry = await prepare(repo, graph)
    assert retry[-1].type == EventType.SUPERVISOR_READINESS_READY


async def test_confirming_ends_release_0_13_even_after_a_restart(repo, setup, graph):  # noqa: F811
    await feasibility_accepted(repo, setup)
    _, events = await prepare(repo, graph)
    brief_id = events[-1].data["supervisor_brief"]["brief"]["id"]
    with pytest.raises(ReadinessNotAllowedError):
        await confirm_supervisor_ready(WS, "someone-elses", repo, graph)
    event = await confirm_supervisor_ready(WS, brief_id, repo, _brief_graph({}))
    assert event.type == EventType.SUPERVISOR_READY_CONFIRMED and event.stage == WorkflowState.SUPERVISOR_READY.value
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.SUPERVISOR_READY
    assert snapshot.supervisor_brief.status == SupervisorBriefStatus.CONFIRMED
    with pytest.raises(ReadinessNotAllowedError):
        await confirm_supervisor_ready(WS, brief_id, repo, graph)
