"""
Tests for the Feasibility workflow (Release 0.12, Step 3).
Real graphs, skills, repository and mock search; fake LLM; in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import FeasibilityRunAlreadyRunningError
from app.core.brain.schemas import FeasibilityStatus, WorkflowState
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.feasibility import (
    FeasibilityNotAllowedError,
    accept_feasibility_report,
    build_feasibility_graph,
    start_feasibility,
)
from app.domains.fyp.workflows.feasibility import runner as feasibility_runner
from app.domains.fyp.workflows.feasibility.events import FAILED_MESSAGE
from app.domains.fyp.workflows.technical_plan import approve_technical_plan
from tests.unit.test_ai_strategy_workflow import repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_technical_plan_workflow import _architecture_graph, design, technology_approved
from tests.unit.test_technology_workflow import no_leftover_active_runs  # noqa: F401 (fixture)

WS = "ws-navy"
SEQUENCE = [EventType.FEASIBILITY_STARTED] + [EventType.FEASIBILITY_PROGRESS] * 4 + [EventType.FEASIBILITY_READY]


def _feasibility_graph(setup: dict):
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["feasibility_fake"] = gateway.router.provider("fake")
    return build_feasibility_graph(MemorySaver(), skills=registry)


@pytest.fixture(autouse=True)
def no_leftover_assessments():
    feasibility_runner._active_assessments.clear()
    yield
    feasibility_runner._active_assessments.clear()


@pytest.fixture
def graph(setup):  # noqa: F811
    return _feasibility_graph(setup)


async def technical_plan_approved(repo, setup):  # noqa: F811
    await technology_approved(repo, setup)
    architecture = _architecture_graph(setup)
    _, events = await design(repo, architecture)
    return await approve_technical_plan(WS, events[-1].data["technical_plan"]["plan"]["id"], repo, architecture)


async def assess(repo, graph):  # noqa: F811
    session = await start_feasibility(WS, repo, graph)
    return session, [event async for event in session.events()]


async def test_approving_the_technical_plan_allows_the_feasibility_check(repo, setup):  # noqa: F811
    event = await technical_plan_approved(repo, setup)
    assert event.allowed_actions == [AllowedAction.ASSESS_FEASIBILITY]


async def test_the_check_streams_events_and_pauses_for_acceptance(repo, setup, graph):  # noqa: F811
    await technical_plan_approved(repo, setup)
    _, events = await assess(repo, graph)
    assert [e.type for e in events] == SEQUENCE
    ready = events[-1]
    assert ready.stage == WorkflowState.FEASIBILITY.value and ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.ACCEPT_FEASIBILITY]
    report = ready.data["feasibility"]["report"]["report"]
    assert len(report["dimensions"]) == 13 and report["overall"] in {"high", "medium", "low"}
    assert {d["assessed_by"] for d in report["dimensions"]} == {"facts", "judgement"}
    assert ready.data["feasibility"]["dimension_names"]["ethical_legal"] == "Ethical / legal concerns"
    assert ready.brain_patch["feasibility_overall"] == report["overall"]
    assert (await graph.aget_state({"configurable": {"thread_id": WS}})).next == ("feasibility_review",)
    for event in events[:-1]:
        assert set(event.data) == {"industry", "branch", "label", "steps", "completed_steps", "total_steps"}


async def test_the_check_needs_an_approved_technical_plan_and_runs_once(repo, setup, graph):  # noqa: F811
    await technology_approved(repo, setup)
    with pytest.raises(FeasibilityNotAllowedError):
        await start_feasibility(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_feasibility("nope", repo, graph)


async def test_one_check_at_a_time_and_only_once(repo, setup, graph):  # noqa: F811
    await technical_plan_approved(repo, setup)
    await start_feasibility(WS, repo, graph)
    with pytest.raises(FeasibilityRunAlreadyRunningError):
        await start_feasibility(WS, repo, graph)
    feasibility_runner._active_assessments.clear()
    _, events = await assess(repo, graph)            # the left "running" run is replaced
    assert events[-1].type == EventType.FEASIBILITY_READY
    with pytest.raises(FeasibilityNotAllowedError):
        await start_feasibility(WS, repo, graph)


async def test_a_failure_is_safe_and_can_be_retried(repo, setup, graph):  # noqa: F811
    await technical_plan_approved(repo, setup)
    setup["feasibility_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    _, events = await assess(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.FEASIBILITY_FAILED and failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.ASSESS_FEASIBILITY] and failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    _, retry = await assess(repo, graph)
    assert retry[-1].type == EventType.FEASIBILITY_READY


async def test_accepting_ends_release_0_12_even_after_a_restart(repo, setup, graph):  # noqa: F811
    await technical_plan_approved(repo, setup)
    _, events = await assess(repo, graph)
    report_id = events[-1].data["feasibility"]["report"]["id"]
    with pytest.raises(FeasibilityNotAllowedError):
        await accept_feasibility_report(WS, "someone-elses", repo, graph)
    event = await accept_feasibility_report(WS, report_id, repo, _feasibility_graph({}))
    assert event.type == EventType.FEASIBILITY_ACCEPTED and event.stage == WorkflowState.FEASIBILITY_ACCEPTED.value
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.FEASIBILITY_ACCEPTED
    assert snapshot.feasibility_report.status == FeasibilityStatus.ACCEPTED
    with pytest.raises(FeasibilityNotAllowedError):
        await accept_feasibility_report(WS, report_id, repo, graph)
