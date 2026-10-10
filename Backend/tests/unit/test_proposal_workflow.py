"""
Tests for the Proposal workflow (Release 0.14, Step 3) — the end of the FYP journey.
Real graphs, skills, repository and mock search; fake LLM; in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.core.brain.repository import ProposalRunAlreadyRunningError
from app.core.brain.schemas import MAX_PROPOSAL_REWRITES, ProposalSectionId, ProposalStatus, WorkflowState
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import ProjectNotFoundError
from app.domains.fyp.workflows.proposal import (
    ProposalNotAllowedError,
    build_proposal_graph,
    finalize_proposal,
    start_proposal,
    start_proposal_rewrite,
)
from app.domains.fyp.workflows.proposal import runner as proposal_runner
from app.domains.fyp.workflows.proposal.events import FAILED_MESSAGE, REWRITE_FAILED_MESSAGE
from app.domains.fyp.workflows.supervisor_readiness import confirm_supervisor_ready
from tests.unit.test_ai_strategy_workflow import repo, setup  # noqa: F401 (fixtures)
from tests.unit.test_supervisor_readiness_workflow import _brief_graph, feasibility_accepted, no_leftover_briefs, prepare  # noqa: F401
from tests.unit.test_technology_workflow import no_leftover_active_runs  # noqa: F401 (fixture)

WS = "ws-navy"
SEQUENCE = [EventType.PROPOSAL_STARTED] + [EventType.PROPOSAL_PROGRESS] * 6 + [EventType.PROPOSAL_READY]
S = ProposalSectionId


def _proposal_graph(setup: dict):
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    setup["proposal_fake"] = gateway.router.provider("fake")
    return build_proposal_graph(MemorySaver(), skills=registry)


@pytest.fixture(autouse=True)
def no_leftover_proposals():
    proposal_runner._active_proposals.clear()
    yield
    proposal_runner._active_proposals.clear()


@pytest.fixture
def graph(setup):  # noqa: F811
    return _proposal_graph(setup)


async def supervisor_ready(repo, setup):  # noqa: F811
    await feasibility_accepted(repo, setup)
    briefs = _brief_graph(setup)
    _, events = await prepare(repo, briefs)
    return await confirm_supervisor_ready(WS, events[-1].data["supervisor_brief"]["brief"]["id"], repo, briefs)


async def write(repo, graph):  # noqa: F811
    session = await start_proposal(WS, repo, graph)
    return session, [event async for event in session.events()]


async def rewrite(repo, graph, section=S.INTRODUCTION):  # noqa: F811
    session = await start_proposal_rewrite(WS, section, repo, graph)
    return session, [event async for event in session.events()]


async def written(repo, setup, graph):  # noqa: F811
    await supervisor_ready(repo, setup)
    _, events = await write(repo, graph)
    return events[-1]


def sections_of(event) -> list[dict]:
    return event.data["proposal"]["proposal"]["proposal"]["sections"]


async def test_confirming_readiness_allows_the_proposal(repo, setup):  # noqa: F811
    event = await supervisor_ready(repo, setup)
    assert event.allowed_actions == [AllowedAction.GENERATE_PROPOSAL]


async def test_writing_streams_events_and_pauses_for_review(repo, setup, graph):  # noqa: F811
    await supervisor_ready(repo, setup)
    _, events = await write(repo, graph)
    assert [e.type for e in events] == SEQUENCE
    ready = events[-1]
    assert ready.stage == WorkflowState.PROPOSAL_GENERATION.value and ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.FINALIZE_PROPOSAL, AllowedAction.REWRITE_PROPOSAL_SECTION]
    assert [s["id"] for s in sections_of(ready)] == [s.value for s in S]
    assert ready.data["proposal"]["rewritable_sections"][0] == "introduction"
    labels = [e.data["label"] for e in events[1:-1]]
    assert "Writing the solution, aim, objectives and method" in labels
    assert (await graph.aget_state({"configurable": {"thread_id": WS}})).next == ("proposal_review",)


async def test_writing_needs_a_ready_student_and_runs_once(repo, setup, graph):  # noqa: F811
    await feasibility_accepted(repo, setup)
    with pytest.raises(ProposalNotAllowedError):
        await start_proposal(WS, repo, graph)
    with pytest.raises(ProjectNotFoundError):
        await start_proposal("nope", repo, graph)


async def test_one_proposal_at_a_time_and_failures_are_safe(repo, setup, graph):  # noqa: F811
    await supervisor_ready(repo, setup)
    await start_proposal(WS, repo, graph)
    with pytest.raises(ProposalRunAlreadyRunningError):
        await start_proposal(WS, repo, graph)
    proposal_runner._active_proposals.clear()
    setup["proposal_fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    _, events = await write(repo, graph)
    failed = events[-1]
    assert failed.type == EventType.PROPOSAL_FAILED and failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.GENERATE_PROPOSAL] and failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    _, retry = await write(repo, graph)
    assert retry[-1].type == EventType.PROPOSAL_READY


async def test_a_rewrite_changes_one_section_and_rewrites_are_limited(repo, setup, graph):  # noqa: F811
    first = await written(repo, setup, graph)
    with pytest.raises(ProposalNotAllowedError, match="can't be rewritten"):
        await start_proposal_rewrite(WS, S.DATASET, repo, graph)
    setup["proposal_fake"].script("fake-model", [LLMUnavailable("down")])
    _, events = await rewrite(repo, graph)
    assert events[-1].status == EventStatus.AWAITING_USER and events[-1].data["message"] == REWRITE_FAILED_MESSAGE
    _, events = await rewrite(repo, graph)
    ready = events[-1]
    changed = [a["id"] for a, b in zip(sections_of(first), sections_of(ready)) if a != b]
    assert changed == ["introduction"]
    assert ready.data["proposal"]["rewrites_left"] == MAX_PROPOSAL_REWRITES - 1
    for _ in range(MAX_PROPOSAL_REWRITES - 1):
        _, events = await rewrite(repo, _proposal_graph({}))            # also after a restart
    assert events[-1].allowed_actions == [AllowedAction.FINALIZE_PROPOSAL]
    with pytest.raises(ProposalNotAllowedError, match="rewrites have been used"):
        await start_proposal_rewrite(WS, S.AIM, repo, graph)


async def test_finalizing_completes_the_journey_even_after_a_restart(repo, setup, graph):  # noqa: F811
    ready = await written(repo, setup, graph)
    proposal_id = ready.data["proposal"]["proposal"]["id"]
    with pytest.raises(ProposalNotAllowedError):
        await finalize_proposal(WS, "someone-elses", repo, graph)
    event = await finalize_proposal(WS, proposal_id, repo, _proposal_graph({}))
    assert event.type == EventType.PROPOSAL_FINALIZED and event.stage == WorkflowState.COMPLETE.value
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.COMPLETE
    assert snapshot.proposal.status == ProposalStatus.FINAL
    with pytest.raises(ProposalNotAllowedError):
        await start_proposal_rewrite(WS, S.AIM, repo, graph)
