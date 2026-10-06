"""
Tests for the FYP Design workflow (Release 0.5, Step 3).

Covers:
  - the graph running classify_area and design_fyp (skills via the registry)
    and pausing at fyp_review (mandatory HITL)
  - the event sequence and what is saved in the Project Brain
  - controlled redesigns, the limit of 3, and approval
  - "Why this FYP?" built only from stored evidence
  - safe failures, retries, and recovery after a restart

Everything is real (graphs, skills, gateway, repository) except the language
model, which is FakeLLMProvider, and an in-memory database.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.brain.models import Base
from app.core.brain.repository import FYPDesignRunAlreadyRunningError, WorkspaceBrainRepository
from app.core.brain.schemas import (
    MAX_FYP_ADJUSTMENTS,
    FYPAdjustment,
    FYPDesignRunKind,
    FYPDesignRunStatus,
    FYPDesignStatus,
    WorkflowState,
)
from app.core.config.settings import Settings
from app.core.events import AllowedAction, EventStatus, EventType
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.design_fyp import INSTRUCTIONS
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import (
    ProjectNotFoundError,
    build_discovery_graph,
    choose_problem,
    problem_runner,
    research_runner,
)
from app.domains.fyp.workflows.fyp_design import (
    FYPDesignNotAllowedError,
    approve_fyp,
    build_fyp_design_graph,
    start_fyp_design,
    start_fyp_redesign,
)
from app.domains.fyp.workflows.fyp_design import runner as fyp_runner
from app.domains.fyp.workflows.fyp_design.events import FAILED_MESSAGE, REDESIGN_FAILED_MESSAGE
from app.domains.fyp.workflows.fyp_design.runner import INTERRUPTED_ERROR
from tests.unit.test_problem_workflow import extract, researched

WS = "ws-navy"

FIRST_DESIGN_SEQUENCE = [
    EventType.FYP_DESIGN_STARTED,
    EventType.FYP_DESIGN_PROGRESS,      # finding where your project fits
    EventType.AREA_CLASSIFIED,
    EventType.FYP_DESIGN_PROGRESS,      # designing
    EventType.FYP_DESIGN_PROGRESS,      # checking
    EventType.FYP_DESIGN_PROGRESS,      # saving
    EventType.FYP_DIRECTION_READY,
]
REDESIGN_SEQUENCE = [
    EventType.FYP_DESIGN_STARTED,
    EventType.FYP_DESIGN_PROGRESS,      # redesigning
    EventType.FYP_DESIGN_PROGRESS,      # checking
    EventType.FYP_DESIGN_PROGRESS,      # saving
    EventType.FYP_DIRECTION_READY,
]
GOOD_AREA = {"functional_area": "Maritime Surveillance", "specific_area": "Vessel Behavior Monitoring",
             "explanation": "The problem is about how ships move."}


# ── Fixtures and helpers ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_leftover_active_runs():
    for active in (research_runner._active_research, problem_runner._active_extractions, fyp_runner._active_designs):
        active.clear()
    yield
    for active in (research_runner._active_research, problem_runner._active_extractions, fyp_runner._active_designs):
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
    """Both workflow graphs sharing one registry with real skills and a fake-mode LLM."""
    gateway = build_llm_gateway(Settings(_env_file=None))
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), gateway)
    return {
        "discovery": build_discovery_graph(MemorySaver(), skills=registry),
        "fyp": build_fyp_design_graph(MemorySaver(), skills=registry),
        "registry": registry,
        "fake": gateway.router.provider("fake"),
    }


@pytest.fixture
def graph(setup):
    return setup["fyp"]


async def chosen(repo, setup, workspace_id=WS):
    """Research, find problems and choose the first one — as the API does."""
    await researched(repo, setup["discovery"], workspace_id)
    await extract(repo, setup["discovery"], workspace_id)
    options = await repo.list_problem_candidates(workspace_id)
    await choose_problem(workspace_id, options[0].id, repo, setup["discovery"])
    return options[0]


async def design(repo, graph, workspace_id=WS):
    session = await start_fyp_design(workspace_id, repo, graph)
    return session, [event async for event in session.events()]


async def redesign(repo, graph, adjustment=FYPAdjustment.MAKE_SIMPLER, note=None, workspace_id=WS):
    session = await start_fyp_redesign(workspace_id, adjustment, note, repo, graph)
    return session, [event async for event in session.events()]


async def graph_state(graph, workspace_id=WS):
    return await graph.aget_state({"configurable": {"thread_id": workspace_id}})


def waiting_at_review(state) -> bool:
    return bool(state.tasks) and state.tasks[0].name == "fyp_review" and bool(state.tasks[0].interrupts)


# ── First design ──────────────────────────────────────────────────────────────

async def test_first_design_event_sequence(repo, setup, graph):
    await chosen(repo, setup)
    _, events = await design(repo, graph)
    assert [e.type for e in events] == FIRST_DESIGN_SEQUENCE
    assert all(e.workflow == "fyp_design" for e in events)


async def test_area_and_design_are_saved_and_the_workflow_waits_for_review(repo, setup, graph):
    problem = await chosen(repo, setup)

    session, events = await design(repo, graph)

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.FYP_DESIGN
    assert snapshot.functional_area.problem_id == problem.id
    assert snapshot.fyp_design.version == 1
    assert snapshot.fyp_design.status == FYPDesignStatus.DRAFT
    assert session.run.status == FYPDesignRunStatus.COMPLETE
    assert (session.run.provider, session.run.model) == ("fake", "fake-model")

    state = await graph_state(graph)
    assert waiting_at_review(state)
    assert state.values["design_id"] == snapshot.fyp_design.id      # graph and Brain agree


async def test_area_classified_event_reveals_the_area_and_moves_the_stage(repo, setup, graph):
    await chosen(repo, setup)
    _, events = await design(repo, graph)

    area_event = next(e for e in events if e.type == EventType.AREA_CLASSIFIED)
    assert area_event.stage == WorkflowState.AREA_CLASSIFICATION.value
    assert area_event.data["area"]["functional_area"]
    assert area_event.brain_patch["workflow_state"] == "AREA_CLASSIFICATION"
    assert events[0].stage == WorkflowState.PROBLEM_SELECTED.value


async def test_ready_event_lets_the_student_approve_or_adjust(repo, setup, graph):
    await chosen(repo, setup)
    _, events = await design(repo, graph)

    ready = events[-1]
    assert ready.status == EventStatus.AWAITING_USER
    assert ready.stage == WorkflowState.FYP_DESIGN.value
    assert ready.allowed_actions == [AllowedAction.APPROVE_FYP_DIRECTION, AllowedAction.ADJUST_FYP_DIRECTION]
    fyp = ready.data["fyp"]
    assert fyp["design"]["version"] == 1
    assert (fyp["adjustments_used"], fyp["adjustments_left"], fyp["max_adjustments"]) == (0, 3, 3)
    assert ready.brain_patch["fyp_title"] == fyp["design"]["title"]
    assert ready.brain_patch["fyp_adjustments_left"] == 3


async def test_why_this_fyp_comes_only_from_stored_evidence(repo, setup, graph):
    problem = await chosen(repo, setup)
    _, events = await design(repo, graph)

    why = events[-1].data["fyp"]["why_this_fyp"]
    design_data = events[-1].data["fyp"]["design"]
    assert why["where_the_problem_came_from"] == problem.real_world_problem
    assert why["what_organizations_are_doing"] == problem.observed_solutions
    assert [s["evidence_source_id"] for s in why["evidence"]] == [s.evidence_source_id for s in problem.evidence]
    assert set(why["organizations"]) == {s.organization for s in problem.evidence}
    assert why["how_grey_made_it_student_sized"] == design_data["scope_reduction"]


async def test_events_never_contain_prompts(repo, setup, graph):
    await chosen(repo, setup)
    _, events = await design(repo, graph)
    assert all(INSTRUCTIONS[:60] not in e.model_dump_json() for e in events)


# ── Redesigns ─────────────────────────────────────────────────────────────────

async def test_a_redesign_saves_a_new_version(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)

    session, events = await redesign(repo, graph, FYPAdjustment.CHANGE_TARGET_USER, note="  For port staff  ")

    assert [e.type for e in events] == REDESIGN_SEQUENCE
    assert events[1].data["label"] == "Redesigning your FYP"
    versions = await repo.list_fyp_designs(WS)
    assert [(d.version, d.status) for d in versions] == [(1, FYPDesignStatus.SUPERSEDED), (2, FYPDesignStatus.DRAFT)]
    assert (versions[1].adjustment, versions[1].note) == (FYPAdjustment.CHANGE_TARGET_USER, "For port staff")
    assert versions[1].target_user != versions[0].target_user
    assert events[-1].data["fyp"]["adjustments_left"] == 2
    assert waiting_at_review(await graph_state(graph))


async def test_the_model_is_sent_the_previous_design_and_the_controlled_request(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    setup["fake"].calls.clear()

    await redesign(repo, graph, FYPAdjustment.REDUCE_COMPLEXITY)

    sent = setup["fake"].calls[0].input_json
    assert "previous_design" in sent and "Reduce the implementation effort" in sent


async def test_after_three_redesigns_only_approve_remains(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    for adjustment in list(FYPAdjustment)[:MAX_FYP_ADJUSTMENTS]:
        _, events = await redesign(repo, graph, adjustment)

    assert events[-1].allowed_actions == [AllowedAction.APPROVE_FYP_DIRECTION]
    assert events[-1].data["fyp"]["adjustments_left"] == 0
    with pytest.raises(FYPDesignNotAllowedError, match="redesigns"):
        await start_fyp_redesign(WS, FYPAdjustment.MAKE_SIMPLER, None, repo, graph)


async def test_review_rejects_an_uncontrolled_adjustment(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    with pytest.raises(ValueError):
        await graph.ainvoke(Command(resume={"action": "adjust", "adjustment": "more_ai"}),
                            {"configurable": {"thread_id": WS}})


# ── Approval ──────────────────────────────────────────────────────────────────

async def test_approval_ends_the_workflow_at_approved_fyp(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    draft = await repo.get_current_fyp_design(WS)

    event = await approve_fyp(WS, draft.id, repo, graph)

    assert event.type == EventType.FYP_DIRECTION_APPROVED
    assert event.stage == WorkflowState.APPROVED_FYP.value
    assert event.status == EventStatus.COMPLETE
    assert event.allowed_actions == []
    assert event.data["fyp"]["design"]["status"] == "approved"
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.APPROVED_FYP
    state = await graph_state(graph)
    assert state.next == ()                                     # the workflow is finished
    assert state.values["approved_design_id"] == draft.id


async def test_an_older_version_cannot_be_approved(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    first = await repo.get_current_fyp_design(WS)
    await redesign(repo, graph)

    with pytest.raises(FYPDesignNotAllowedError, match="current"):
        await approve_fyp(WS, first.id, repo, graph)


async def test_nothing_can_change_after_approval(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    draft = await repo.get_current_fyp_design(WS)
    await approve_fyp(WS, draft.id, repo, graph)

    with pytest.raises(FYPDesignNotAllowedError):
        await start_fyp_redesign(WS, FYPAdjustment.MAKE_SIMPLER, None, repo, graph)
    with pytest.raises(FYPDesignNotAllowedError):
        await start_fyp_design(WS, repo, graph)
    with pytest.raises(FYPDesignNotAllowedError):
        await approve_fyp(WS, draft.id, repo, graph)


# ── Not allowed ───────────────────────────────────────────────────────────────

async def test_design_needs_a_chosen_problem(repo, setup, graph):
    await researched(repo, setup["discovery"])
    with pytest.raises(FYPDesignNotAllowedError):
        await start_fyp_design(WS, repo, graph)


async def test_unknown_project(repo, graph):
    with pytest.raises(ProjectNotFoundError):
        await start_fyp_design("nope", repo, graph)


async def test_first_design_cannot_run_twice(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    with pytest.raises(FYPDesignNotAllowedError):
        await start_fyp_design(WS, repo, graph)


async def test_only_one_design_at_a_time(repo, setup, graph):
    await chosen(repo, setup)
    await start_fyp_design(WS, repo, graph)              # started, not yet run
    with pytest.raises(FYPDesignRunAlreadyRunningError):
        await start_fyp_design(WS, repo, graph)


# ── Failures and retries ──────────────────────────────────────────────────────

async def test_a_failed_first_design_is_safe_and_can_be_retried(repo, setup, graph):
    await chosen(repo, setup)
    setup["fake"].script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])

    session, events = await design(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.FYP_DESIGN_FAILED
    assert failed.status == EventStatus.BLOCKED
    assert failed.allowed_actions == [AllowedAction.DESIGN_FYP]
    assert failed.data["message"] == FAILED_MESSAGE
    assert "internal detail" not in failed.model_dump_json()
    assert session.run.status == FYPDesignRunStatus.FAILED
    assert "internal detail" in session.run.error                # kept on the run for debugging
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.PROBLEM_SELECTED

    _, events = await design(repo, graph)
    assert [e.type for e in events] == FIRST_DESIGN_SEQUENCE


async def test_a_retry_after_the_area_was_saved_skips_the_area(repo, setup, graph):
    await chosen(repo, setup)
    setup["fake"].script("fake-model", [GOOD_AREA, LLMUnavailable("down")])
    _, events = await design(repo, graph)
    assert events[-1].type == EventType.FYP_DESIGN_FAILED
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.AREA_CLASSIFICATION
    assert snapshot.functional_area.functional_area == "Maritime Surveillance"

    session, events = await design(repo, graph)

    assert session.recovered_workflow is True
    assert EventType.AREA_CLASSIFIED not in [e.type for e in events]
    assert events[-1].type == EventType.FYP_DIRECTION_READY
    assert events[-1].data["fyp"]["area"]["functional_area"] == "Maritime Surveillance"


async def test_a_failed_redesign_keeps_the_draft_and_the_adjustment(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    setup["fake"].script("fake-model", [LLMUnavailable("down")])

    _, events = await redesign(repo, graph)

    failed = events[-1]
    assert failed.type == EventType.FYP_DESIGN_FAILED
    assert failed.status == EventStatus.AWAITING_USER
    assert failed.allowed_actions == [AllowedAction.APPROVE_FYP_DIRECTION, AllowedAction.ADJUST_FYP_DIRECTION]
    assert failed.data["message"] == REDESIGN_FAILED_MESSAGE
    assert failed.data["fyp"]["design"]["version"] == 1
    assert await repo.count_fyp_adjustments(WS) == 0

    _, events = await redesign(repo, graph)                    # the workflow is rebuilt at review
    assert events[-1].type == EventType.FYP_DIRECTION_READY
    assert events[-1].data["fyp"]["design"]["version"] == 2


async def test_a_run_left_running_by_a_stopped_server_is_replaced(repo, setup, graph):
    await chosen(repo, setup)
    leftover = await repo.start_fyp_design_run(WS, FYPDesignRunKind.INITIAL)

    _, events = await design(repo, graph)

    assert events[-1].type == EventType.FYP_DIRECTION_READY
    runs = await repo.get_snapshot(WS)
    assert runs.fyp_design_run.id != leftover.id
    old = await repo._require_fyp_run_record(leftover.id)
    assert (old.status, old.error) == ("failed", INTERRUPTED_ERROR)


# ── Restart safety ────────────────────────────────────────────────────────────

async def test_approval_works_after_a_restart(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    draft = await repo.get_current_fyp_design(WS)

    restarted = build_fyp_design_graph(MemorySaver(), skills=setup["registry"])   # memory lost
    event = await approve_fyp(WS, draft.id, repo, restarted)

    assert event.stage == WorkflowState.APPROVED_FYP.value
    assert (await graph_state(restarted)).values["approved_design_id"] == draft.id


async def test_redesign_works_after_a_restart(repo, setup, graph):
    await chosen(repo, setup)
    await design(repo, graph)
    await redesign(repo, graph)

    restarted = build_fyp_design_graph(MemorySaver(), skills=setup["registry"])
    session, events = await redesign(repo, restarted, FYPAdjustment.CHANGE_SYSTEM_FOCUS)

    assert session.recovered_workflow is True
    assert events[-1].data["fyp"]["design"]["version"] == 3
    assert (await graph_state(restarted)).values["adjustments_used"] == 2


async def test_first_design_works_after_a_restart(repo, setup, graph):
    await chosen(repo, setup)
    restarted = build_fyp_design_graph(MemorySaver(), skills=setup["registry"])
    _, events = await design(repo, restarted)
    assert events[-1].type == EventType.FYP_DIRECTION_READY
