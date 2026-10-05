"""
Tests for the evidence_research step of the Discovery workflow (Release 0.2).

Covers:
  - the workflow calling the skill through the SkillRegistry
  - the progress event sequence and its safe content
  - research-run persistence in the Project Brain
  - failure, retry, and recovery after a restart or a dropped connection

Everything is real (graph, skill, repository) except the search provider in
the failure tests, and an in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.brain.models import Base, ResearchRunRecord
from app.core.brain.repository import ResearchAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import ResearchStatus, WorkflowState
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.skills.base import Skill, SkillMetadata
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import SearchProvider, SearchProviderError, SearchQuery
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.research_evidence import ResearchEvidenceOutput, ResearchSummary
from app.domains.fyp.workflows.discovery import (
    ProjectNotFoundError,
    ResearchNotAllowedError,
    build_discovery_graph,
    start_evidence_research,
)
from app.domains.fyp.workflows.discovery import research_runner
from app.domains.fyp.workflows.discovery.research_events import FAILED_MESSAGE, RESEARCH_STEPS

WS = "ws-navy"

EXPECTED_SEQUENCE = [
    EventType.RESEARCH_STARTED,
    *[EventType.SEARCHING_SOURCES, EventType.SOURCES_FOUND] * 6,   # the six research steps (0.4)
    EventType.EVALUATING_EVIDENCE,
    EventType.STORING_EVIDENCE,
    EventType.RESEARCH_COMPLETED,
]


# ── Fixtures and helpers ──────────────────────────────────────────────────────

class BrokenSearch(SearchProvider):
    """A provider that is always down."""
    name = "broken"

    async def search(self, query: SearchQuery):
        raise SearchProviderError("connection refused by search vendor (internal detail)")


def registry_with(search: SearchProvider) -> SkillRegistry:
    registry = SkillRegistry()
    register_fyp_skills(registry, search)
    return registry


@pytest.fixture(autouse=True)
def no_leftover_active_research():
    research_runner._active_research.clear()
    yield
    research_runner._active_research.clear()


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield WorkspaceBrainRepository(session)
    await engine.dispose()


@pytest.fixture
def graph():
    return build_discovery_graph(MemorySaver(), skills=registry_with(MockSearchProvider()))


async def ready_for_research(repo, graph, workspace_id=WS, industry="Defense", branch="Navy"):
    """Do what the API routes do: start → industry → branch, in both the graph and the Brain."""
    config = {"configurable": {"thread_id": workspace_id}}
    await repo.create_workspace(workspace_id)
    await graph.ainvoke({"workspace_id": workspace_id, "workflow_state": "INDUSTRY_SELECTION",
                         "industry": None, "branch": None}, config=config)
    await graph.ainvoke(Command(resume=industry), config=config)
    await repo.apply_decision(workspace_id, "industry", industry)
    await graph.ainvoke(Command(resume=branch), config=config)
    await repo.apply_decision(workspace_id, "branch", branch)
    await repo.update_workflow_state(workspace_id, WorkflowState.EVIDENCE_RESEARCH)


async def research(repo, graph, workspace_id=WS):
    session = await start_evidence_research(workspace_id, repo, graph, provider_name="mock")
    return session, [event async for event in session.events()]


# ── Skill Registry use ────────────────────────────────────────────────────────

class _SpySkill(Skill):
    """Stands in for the real skill, to prove the workflow looks it up by name."""
    metadata = SkillMetadata(name="research_evidence", description="spy")

    def __init__(self):
        self.inputs = []

    async def execute(self, input: BaseModel, on_progress=None):
        self.inputs.append(input)
        return ResearchEvidenceOutput(
            industry=input.industry, branch=input.branch, sources=[], queries_run=[],
            summary=ResearchSummary(total_sources=0, high_quality_count=0, by_tier={},
                                    by_category={}, provider="spy"),
        )


async def test_workflow_gets_the_skill_from_the_registry(repo):
    spy = _SpySkill()
    registry = SkillRegistry()
    registry.register(spy)
    graph = build_discovery_graph(MemorySaver(), skills=registry)
    await ready_for_research(repo, graph)

    _, events = await research(repo, graph)

    assert len(spy.inputs) == 1
    assert (spy.inputs[0].industry, spy.inputs[0].branch) == ("Defense", "Navy")
    assert events[-1].type == EventType.RESEARCH_COMPLETED


async def test_missing_skill_fails_safely(repo):
    graph = build_discovery_graph(MemorySaver(), skills=SkillRegistry())   # empty registry
    await ready_for_research(repo, graph)

    session, events = await research(repo, graph)

    assert events[-1].type == EventType.RESEARCH_FAILED
    assert session.run.status == ResearchStatus.FAILED
    assert "research_evidence" in session.run.error


# ── Happy path ────────────────────────────────────────────────────────────────

async def test_event_sequence(repo, graph):
    await ready_for_research(repo, graph)
    _, events = await research(repo, graph)
    assert [e.type for e in events] == EXPECTED_SEQUENCE


async def test_research_is_persisted_and_workflow_pauses_before_problems(repo, graph):
    await ready_for_research(repo, graph)

    session, events = await research(repo, graph)

    snapshot = await repo.get_snapshot(WS)
    evidence = await repo.list_evidence(WS)
    assert snapshot.research.status == ResearchStatus.COMPLETE
    assert snapshot.research.id == session.run.id
    assert snapshot.workflow_state == WorkflowState.EVIDENCE_RESEARCH      # no v0.3 stages
    assert len(evidence) == session.run.sources_found > 0
    assert all(e.provider == "mock" for e in evidence)
    # The completed event reports exactly what was saved.
    done = events[-1]
    assert done.brain_patch == {
        "research_status": "complete",
        "evidence_count": len(evidence),
        "high_quality_evidence_count": session.run.high_quality_count,
    }
    assert done.data["summary"]["total_sources"] == len(evidence)
    assert done.data["summary"]["startups_confirmed"] >= 1
    assert set(done.data["summary"]["by_category"]) == {
        "organizations", "official_sources", "research", "datasets", "news",
    }
    # The workflow now pauses before problem extraction (Release 0.3).
    state = await graph.aget_state({"configurable": {"thread_id": WS}})
    assert state.next == ("problem_extraction",)


async def test_event_envelope_fields(repo, graph):
    await ready_for_research(repo, graph)
    _, events = await research(repo, graph)

    assert all(e.stage == "EVIDENCE_RESEARCH" and e.workspace_id == WS for e in events)
    assert all(e.status == EventStatus.RUNNING for e in events[:-1])
    assert events[-1].status == EventStatus.COMPLETE
    assert events[-1].allowed_actions == [AllowedAction.EXTRACT_PROBLEMS]   # problems are found next (0.3)
    assert all(e.data["branch"] == "Navy" for e in events)


async def test_checklist_and_counts_progress_forward(repo, graph):
    await ready_for_research(repo, graph)
    _, events = await research(repo, graph)

    assert [s["state"] for s in events[0].data["steps"]] == ["pending"] * len(RESEARCH_STEPS)
    assert [s["state"] for s in events[-1].data["steps"]] == ["done"] * len(RESEARCH_STEPS)
    completed = [e.data["completed_steps"] for e in events]
    sources = [e.data["sources_found"] for e in events]
    assert completed == sorted(completed) and sources == sorted(sources)
    for event in events:   # never more than one step active at a time
        assert sum(s["state"] == "active" for s in event.data["steps"]) <= 1


async def test_events_only_contain_safe_activity(repo, graph):
    """No queries, prompts, snippets or reasoning — only labels, the checklist and counts."""
    await ready_for_research(repo, graph)
    _, events = await research(repo, graph)

    allowed_keys = {"industry", "branch", "label", "steps", "completed_steps", "total_steps",
                    "sources_found", "high_quality_sources", "summary", "message"}
    safe_labels = {label for _, label in RESEARCH_STEPS} | {"Starting research", "Research complete"}
    for event in events:
        assert set(event.data) <= allowed_keys
        assert event.data["label"] in safe_labels
        assert "query" not in str(event.data) and '"Navy"' not in str(event.data)


# ── Preconditions ─────────────────────────────────────────────────────────────

async def test_unknown_project(repo, graph):
    with pytest.raises(ProjectNotFoundError):
        await start_evidence_research("ghost", repo, graph, provider_name="mock")


async def test_cannot_research_before_branch_is_chosen(repo, graph):
    await repo.create_workspace(WS)
    await repo.apply_decision(WS, "industry", "Defense")

    with pytest.raises(ResearchNotAllowedError):
        await start_evidence_research(WS, repo, graph, provider_name="mock")
    assert await repo.get_latest_research_run(WS) is None


async def test_cannot_start_research_twice_at_once(repo, graph):
    await ready_for_research(repo, graph)
    first = await start_evidence_research(WS, repo, graph, provider_name="mock")

    with pytest.raises(ResearchAlreadyRunningError):
        await start_evidence_research(WS, repo, graph, provider_name="mock")

    _ = [e async for e in first.events()]                 # first run finishes…
    _, events = await research(repo, graph)               # …then research can run again
    assert events[-1].type == EventType.RESEARCH_COMPLETED


# ── Failure and retry ─────────────────────────────────────────────────────────

async def test_provider_failure_is_safe_and_retryable(repo):
    broken = build_discovery_graph(MemorySaver(), skills=registry_with(BrokenSearch()))
    await ready_for_research(repo, broken)

    session, events = await research(repo, broken)

    failed = events[-1]
    assert [e.type for e in events][:2] == [EventType.RESEARCH_STARTED, EventType.SEARCHING_SOURCES]
    assert failed.type == EventType.RESEARCH_FAILED
    assert failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.START_RESEARCH]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in str(failed.model_dump())      # real error is not sent…
    assert "internal detail" in session.run.error                   # …but is stored on the run
    assert (await repo.get_snapshot(WS)).research.status == ResearchStatus.FAILED


async def test_failed_research_keeps_earlier_evidence(repo, graph):
    await ready_for_research(repo, graph)
    await research(repo, graph)
    before = await repo.list_evidence(WS)

    # Same project, but now the search provider is down (e.g. after a config change).
    broken = build_discovery_graph(MemorySaver(), skills=registry_with(BrokenSearch()))
    _, events = await research(repo, broken)

    assert events[-1].type == EventType.RESEARCH_FAILED
    assert await repo.list_evidence(WS) == before


async def test_retry_after_failure_succeeds(repo):
    broken = build_discovery_graph(MemorySaver(), skills=registry_with(BrokenSearch()))
    await ready_for_research(repo, broken)
    await research(repo, broken)

    healthy = build_discovery_graph(MemorySaver(), skills=registry_with(MockSearchProvider()))
    _, events = await research(repo, healthy)

    assert events[-1].type == EventType.RESEARCH_COMPLETED
    assert len(await repo.list_evidence(WS)) > 0


# ── Restart and recovery ──────────────────────────────────────────────────────

async def test_research_works_after_a_restart(repo, graph):
    """The in-memory workflow is lost on restart; it is rebuilt from the Project Brain."""
    await ready_for_research(repo, graph)

    restarted = build_discovery_graph(MemorySaver(), skills=registry_with(MockSearchProvider()))
    session, events = await research(repo, restarted)

    assert session.recovered_workflow is True
    assert [e.type for e in events] == EXPECTED_SEQUENCE
    assert all("Navy" in e.data["branch"] for e in events)


async def test_normal_run_does_not_need_recovery(repo, graph):
    await ready_for_research(repo, graph)
    session, _ = await research(repo, graph)
    assert session.recovered_workflow is False


async def test_run_left_running_by_a_stopped_server_is_replaced(repo, graph):
    await ready_for_research(repo, graph)
    orphan = await repo.start_research_run(WS, provider="mock")    # server "died" during this run

    session, events = await research(repo, graph)

    assert events[-1].type == EventType.RESEARCH_COMPLETED
    assert session.run.id != orphan.id
    # The orphaned run is now recorded as interrupted, not left "running" forever.
    record = await repo._session.get(ResearchRunRecord, orphan.id)
    assert record.status == ResearchStatus.FAILED.value
    assert record.error == research_runner.INTERRUPTED_ERROR


async def test_dropped_connection_mid_research_can_be_recovered(repo, graph):
    """If the browser disconnects mid-stream, the next attempt cleans up and finishes."""
    await ready_for_research(repo, graph)
    session = await start_evidence_research(WS, repo, graph, provider_name="mock")

    stream = session.events()
    await stream.__anext__()          # research_started
    await stream.__anext__()          # searching_sources
    await stream.aclose()             # browser went away

    assert WS not in research_runner._active_research
    assert (await repo.get_snapshot(WS)).research.status == ResearchStatus.RUNNING

    _, events = await research(repo, graph)
    assert events[-1].type == EventType.RESEARCH_COMPLETED


async def test_research_can_be_run_again_after_completing(repo, graph):
    await ready_for_research(repo, graph)
    first, _ = await research(repo, graph)

    second, events = await research(repo, graph)

    assert second.recovered_workflow is True          # finished workflow is rewound to research
    assert events[-1].type == EventType.RESEARCH_COMPLETED
    assert {e.research_run_id for e in await repo.list_evidence(WS)} == {second.run.id}


async def test_brain_is_the_source_of_truth_for_industry_and_branch(repo, graph):
    """If the workflow's memory disagrees with the Brain, research uses the Brain."""
    await ready_for_research(repo, graph)
    await repo.apply_decision(WS, "branch", "Air Force")    # Brain changed; graph still says Navy

    session, events = await research(repo, graph)

    assert session.recovered_workflow is True
    assert events[0].data["branch"] == "Air Force"
    evidence = await repo.list_evidence(WS)
    assert all("Air Force" in e.query for e in evidence)
