"""
Tests for problem extraction and selection in the Discovery workflow (Release 0.3, Step 4).

Covers:
  - the graph running problem_extraction (skill via the registry) and pausing
    at problem_selection (mandatory HITL)
  - the event sequence and what is saved in the Project Brain
  - safe failures and retries
  - recovery after a restart, for both extraction and selection

Everything is real (graph, skills, gateway, repository) except the language
model, which is FakeLLMProvider, and an in-memory database.
"""
import json

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.brain.models import Base, ProblemRunRecord
from app.core.brain.readers import SessionEvidenceReader
from app.core.brain.repository import (
    ProblemRunAlreadyRunningError,
    ProblemSelectionError,
    WorkspaceBrainRepository,
)
from app.core.brain.schemas import (
    EvidenceTier,
    ProblemRunStatus,
    ProblemStatus,
    ResearchCategory,
    SourceType,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.problem_extraction import PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import (
    ProblemExtractionNotAllowedError,
    ProjectNotFoundError,
    ResearchNotAllowedError,
    build_discovery_graph,
    choose_problem,
    start_evidence_research,
    start_problem_extraction,
)
from app.domains.fyp.workflows.discovery import problem_runner, research_runner
from app.domains.fyp.workflows.discovery.problem_events import (
    FAILED_MESSAGE,
    NOT_ENOUGH_EVIDENCE_MESSAGE,
    PROBLEM_STEPS,
)
from tests.unit.test_brain_problems import make_source

WS = "ws-navy"

EXPECTED_SEQUENCE = [
    EventType.PROBLEM_EXTRACTION_STARTED,
    EventType.PROBLEM_EXTRACTION_PROGRESS,     # reviewing evidence
    EventType.PROBLEM_EXTRACTION_PROGRESS,     # identifying problems (the LLM call)
    EventType.PROBLEM_EXTRACTION_PROGRESS,     # checking problems
    EventType.PROBLEM_EXTRACTION_PROGRESS,     # saving
    EventType.PROBLEM_OPTIONS_READY,
]


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_leftover_active_runs():
    research_runner._active_research.clear()
    problem_runner._active_extractions.clear()
    yield
    research_runner._active_research.clear()
    problem_runner._active_extractions.clear()


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield WorkspaceBrainRepository(session)
    await engine.dispose()


def make_graph():
    """A fresh graph with real skills, a fake-mode LLM gateway, and its fake provider."""
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    return build_discovery_graph(MemorySaver(), skills=registry), gateway.router.provider("fake")


@pytest.fixture
def graph_and_fake():
    return make_graph()


@pytest.fixture
def graph(graph_and_fake):
    return graph_and_fake[0]


async def researched(repo, graph, workspace_id=WS, industry="Defense", branch="Navy"):
    """Do what the API does: start → industry → branch → research, in both the graph and the Brain."""
    config = {"configurable": {"thread_id": workspace_id}}
    await repo.create_workspace(workspace_id)
    await graph.ainvoke({"workspace_id": workspace_id, "workflow_state": "INDUSTRY_SELECTION",
                         "industry": None, "branch": None}, config=config)
    await graph.ainvoke(Command(resume=industry), config=config)
    await repo.apply_decision(workspace_id, "industry", industry)
    await graph.ainvoke(Command(resume=branch), config=config)
    await repo.apply_decision(workspace_id, "branch", branch)
    await repo.update_workflow_state(workspace_id, WorkflowState.EVIDENCE_RESEARCH)
    session = await start_evidence_research(workspace_id, repo, graph, provider_name="mock")
    events = [e async for e in session.events()]
    assert events[-1].type == EventType.RESEARCH_COMPLETED


async def extract(repo, graph, workspace_id=WS):
    session = await start_problem_extraction(workspace_id, repo, graph)
    return session, [event async for event in session.events()]


async def graph_state(graph, workspace_id=WS):
    return await graph.aget_state({"configurable": {"thread_id": workspace_id}})


HALLUCINATED = {"problems": [{
    "title": f"Invented problem {i}", "real_world_problem": "x", "observed_solutions": "x",
    "technical_problem": "x", "task_type": "other", "why_it_matters": "x",
    "possible_fyp_direction": "x", "evidence": [{"ref": f"E{90 + i}", "supporting_point": "made up words here"}],
} for i in range(4)]}


# ── Graph shape ───────────────────────────────────────────────────────────────

async def test_graph_pauses_before_problem_extraction_after_research(repo, graph):
    await researched(repo, graph)
    assert (await graph_state(graph)).next == ("problem_extraction",)


# ── Happy path ────────────────────────────────────────────────────────────────

async def test_event_sequence(repo, graph):
    await researched(repo, graph)
    _, events = await extract(repo, graph)
    assert [e.type for e in events] == EXPECTED_SEQUENCE


async def test_options_are_saved_and_the_project_waits_for_a_choice(repo, graph):
    await researched(repo, graph)

    session, events = await extract(repo, graph)

    options = await repo.list_problem_candidates(WS)
    snapshot = await repo.get_snapshot(WS)
    assert 3 <= len(options) <= 5
    assert snapshot.workflow_state == WorkflowState.PROBLEM_OPTIONS
    assert snapshot.problem_run.status == ProblemRunStatus.COMPLETE
    assert (session.run.provider, session.run.model, session.run.prompt_version) == ("fake", "fake-model", PROMPT_VERSION)

    # The workflow is waiting inside problem_selection with the SAME ids as the Brain.
    state = await graph_state(graph)
    assert state.tasks[0].name == "problem_selection" and state.tasks[0].interrupts
    assert state.values["problem_candidate_ids"] == [o.id for o in options]


async def test_options_ready_event_carries_the_cards_and_their_sources(repo, graph):
    await researched(repo, graph)
    _, events = await extract(repo, graph)
    ready = events[-1]

    assert ready.stage == WorkflowState.PROBLEM_OPTIONS.value
    assert ready.status == EventStatus.AWAITING_USER
    assert ready.allowed_actions == [AllowedAction.SELECT_PROBLEM]
    assert ready.brain_patch["workflow_state"] == "PROBLEM_OPTIONS"
    stored = await repo.list_problem_candidates(WS)
    assert [p["id"] for p in ready.data["problems"]] == [o.id for o in stored]
    first_source = ready.data["problems"][0]["evidence"][0]
    assert first_source["url"].startswith("https://") and first_source["title"]
    assert ready.data["summary"]["provider"] == "fake"
    assert [s["state"] for s in ready.data["steps"]] == ["done"] * len(PROBLEM_STEPS)


async def test_events_only_contain_safe_activity(repo, graph):
    await researched(repo, graph)
    _, events = await extract(repo, graph)
    text = json.dumps([e.model_dump(mode="json") for e in events[:-1]])

    for private in ("instructions", "Rules:", "evidence_reader", "supporting_point"):
        assert private not in text


async def test_the_evidence_reader_is_never_stored_in_workflow_state(repo, graph):
    await researched(repo, graph)
    await extract(repo, graph)
    assert "evidence_reader" not in (await graph_state(graph)).values


# ── Not allowed ───────────────────────────────────────────────────────────────

async def test_unknown_project(repo, graph):
    with pytest.raises(ProjectNotFoundError):
        await start_problem_extraction("does-not-exist", repo, graph)


async def test_cannot_find_problems_before_research_completes(repo, graph):
    await repo.create_workspace(WS)
    await repo.apply_decision(WS, "industry", "Defense")
    await repo.apply_decision(WS, "branch", "Navy")
    await repo.update_workflow_state(WS, WorkflowState.EVIDENCE_RESEARCH)

    with pytest.raises(ProblemExtractionNotAllowedError):
        await start_problem_extraction(WS, repo, graph)


async def test_cannot_find_problems_twice_at_once(repo, graph):
    await researched(repo, graph)
    await start_problem_extraction(WS, repo, graph)

    with pytest.raises(ProblemRunAlreadyRunningError):
        await start_problem_extraction(WS, repo, graph)


async def test_cannot_find_problems_again_once_options_exist(repo, graph):
    await researched(repo, graph)
    await extract(repo, graph)

    with pytest.raises(ProblemExtractionNotAllowedError):
        await start_problem_extraction(WS, repo, graph)


async def test_research_cannot_run_again_once_options_exist(repo, graph):
    await researched(repo, graph)
    await extract(repo, graph)

    with pytest.raises(ResearchNotAllowedError):
        await start_evidence_research(WS, repo, graph, provider_name="mock")


# ── Failures are safe and retryable ───────────────────────────────────────────

async def test_llm_failure_is_safe_and_retryable(repo, graph_and_fake):
    graph, fake = graph_and_fake
    await researched(repo, graph)
    fake.script("fake-model", [LLMUnavailable("all models down (internal detail)")])

    session, events = await extract(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.PROBLEM_EXTRACTION_FAILED
    assert failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.EXTRACT_PROBLEMS]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in json.dumps(failed.model_dump(mode="json"))
    assert session.run.status == ProblemRunStatus.FAILED
    assert "LLMUnavailable" in session.run.error
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.EVIDENCE_RESEARCH

    # Trying again works (the fake model now answers normally).
    _, retry = await extract(repo, graph)
    assert retry[-1].type == EventType.PROBLEM_OPTIONS_READY


async def test_invented_problems_fail_safely_without_padding(repo, graph_and_fake):
    graph, fake = graph_and_fake
    await researched(repo, graph)
    fake.script("fake-model", [HALLUCINATED, HALLUCINATED])

    session, events = await extract(repo, graph)

    assert events[-1].type == EventType.PROBLEM_EXTRACTION_FAILED
    assert "TooFewProblemsError" in session.run.error
    assert await repo.list_problem_candidates(WS) == []


async def test_not_enough_evidence_suggests_researching_again(repo, graph_and_fake):
    graph, fake = graph_and_fake
    await repo.create_workspace(WS)
    await repo.apply_decision(WS, "industry", "Defense")
    await repo.apply_decision(WS, "branch", "Navy")
    await repo.update_workflow_state(WS, WorkflowState.EVIDENCE_RESEARCH)
    run = await repo.start_research_run(WS, provider="mock")
    await repo.complete_research_run(run.id, [make_source(1), make_source(2)])   # only 2 sources

    session, events = await extract(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.PROBLEM_EXTRACTION_FAILED
    assert failed.allowed_actions == [AllowedAction.START_RESEARCH]
    assert failed.data["message"] == NOT_ENOUGH_EVIDENCE_MESSAGE
    assert fake.calls == []                     # the model was never asked


async def test_missing_skill_fails_safely(repo):
    graph = build_discovery_graph(MemorySaver(), skills=_research_only_registry())
    await researched(repo, graph)

    session, events = await extract(repo, graph)

    assert events[-1].type == EventType.PROBLEM_EXTRACTION_FAILED
    assert "problem_extraction" in session.run.error


def _research_only_registry() -> SkillRegistry:
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())        # no LLM → no problem skill
    return registry


# ── Restart and recovery ──────────────────────────────────────────────────────

async def test_extraction_works_after_a_restart(repo, graph):
    await researched(repo, graph)
    restarted, _ = make_graph()

    session, events = await extract(repo, restarted)

    assert session.recovered_workflow is True
    assert [e.type for e in events] == EXPECTED_SEQUENCE


async def test_normal_run_does_not_need_recovery(repo, graph):
    await researched(repo, graph)
    session, _ = await extract(repo, graph)
    assert session.recovered_workflow is False


async def test_run_left_running_by_a_stopped_server_is_replaced(repo, graph):
    await researched(repo, graph)
    orphan = await repo.start_problem_run(WS, (await repo.get_snapshot(WS)).research.id)

    session, events = await extract(repo, graph)

    assert events[-1].type == EventType.PROBLEM_OPTIONS_READY
    record = await repo._session.get(ProblemRunRecord, orphan.id)
    assert record.status == "failed"
    assert record.error == problem_runner.INTERRUPTED_ERROR


async def test_dropped_connection_mid_extraction_can_be_recovered(tmp_path, graph):
    """
    If the browser disconnects mid-stream — even while the skill is reading
    evidence — the next request cleans up and finishes.

    Set up like the real app: a database FILE, a new session per request, and a
    SessionEvidenceReader. (Without that reader, the cut-off read could leave
    SQLite locked and the next attempt would fail with "database is locked".)
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'grey.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with sessions() as first_request:
        repo = WorkspaceBrainRepository(first_request)
        await researched(repo, graph)
        session = await start_problem_extraction(WS, repo, graph, SessionEvidenceReader(sessions))
        stream = session.events()
        await stream.__anext__()          # started
        await stream.__anext__()          # reviewing evidence
        await stream.aclose()             # browser went away

    assert WS not in problem_runner._active_extractions

    async with sessions() as second_request:
        retry = await start_problem_extraction(
            WS, WorkspaceBrainRepository(second_request), graph, SessionEvidenceReader(sessions)
        )
        events = [event async for event in retry.events()]
    assert events[-1].type == EventType.PROBLEM_OPTIONS_READY
    await engine.dispose()


# ── Selecting a problem (HITL resume) ─────────────────────────────────────────

async def test_choosing_a_problem_resumes_the_workflow_and_saves_the_choice(repo, graph):
    await researched(repo, graph)
    await extract(repo, graph)
    options = await repo.list_problem_candidates(WS)
    chosen = options[1]

    event = await choose_problem(WS, chosen.id, repo, graph)

    assert event.type == EventType.PROBLEM_SELECTED
    assert event.stage == WorkflowState.PROBLEM_SELECTED.value
    assert event.status == EventStatus.COMPLETE
    assert event.allowed_actions == []
    assert event.data["problem"]["id"] == chosen.id
    assert event.brain_patch == {
        "workflow_state": "PROBLEM_SELECTED",
        "selected_problem_id": chosen.id,
        "selected_problem_title": chosen.title,
    }
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.PROBLEM_SELECTED
    assert snapshot.selected_problem.id == chosen.id

    state = await graph_state(graph)
    assert state.next == ()                                    # discovery is finished
    assert state.values["selected_problem_id"] == chosen.id


async def test_choosing_works_after_a_restart(repo, graph):
    """The paused selection is rebuilt from the options saved in the Brain."""
    await researched(repo, graph)
    await extract(repo, graph)
    chosen = (await repo.list_problem_candidates(WS))[0]
    restarted, _ = make_graph()

    event = await choose_problem(WS, chosen.id, repo, restarted)

    assert event.type == EventType.PROBLEM_SELECTED
    assert (await graph_state(restarted)).values["selected_problem_id"] == chosen.id


async def test_choosing_an_unknown_problem_is_rejected_and_nothing_changes(repo, graph):
    await researched(repo, graph)
    await extract(repo, graph)

    with pytest.raises(ProblemSelectionError):
        await choose_problem(WS, "invented-id", repo, graph)

    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.PROBLEM_OPTIONS
    assert all(o.status == ProblemStatus.CANDIDATE for o in await repo.list_problem_candidates(WS))


async def test_cannot_choose_before_options_exist(repo, graph):
    await researched(repo, graph)
    with pytest.raises(ProblemSelectionError):
        await choose_problem(WS, "anything", repo, graph)


async def test_cannot_choose_twice(repo, graph):
    await researched(repo, graph)
    await extract(repo, graph)
    first, second = (await repo.list_problem_candidates(WS))[:2]
    await choose_problem(WS, first.id, repo, graph)

    with pytest.raises(ProblemSelectionError):
        await choose_problem(WS, second.id, repo, graph)


async def test_choose_for_unknown_project(repo, graph):
    with pytest.raises(ProjectNotFoundError):
        await choose_problem("does-not-exist", "anything", repo, graph)


# ── Whole journey ─────────────────────────────────────────────────────────────

async def test_full_discovery_journey(repo, graph):
    """Start → industry → branch → research → problems → choice, through the workflow."""
    await researched(repo, graph, industry="Healthcare", branch="Medical Imaging")
    _, events = await extract(repo, graph)
    options = events[-1].data["problems"]

    event = await choose_problem(WS, options[0]["id"], repo, graph)

    snapshot = await repo.get_snapshot(WS)
    assert (snapshot.industry, snapshot.branch) == ("Healthcare", "Medical Imaging")
    assert snapshot.research.status == "complete"
    assert snapshot.workflow_state == WorkflowState.PROBLEM_SELECTED
    assert snapshot.selected_problem.title == options[0]["title"] == event.brain_patch["selected_problem_title"]
