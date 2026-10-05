"""
Tests for the Discovery workflow graph.

Uses an in-memory MemorySaver (not the shared discovery_graph instance)
so each test gets a clean slate with no leftover state from other tests.

How the interrupt pattern works:
  1. ainvoke(initial_state) → graph runs until interrupt() → graph pauses.
  2. ainvoke(Command(resume=value)) → graph resumes from the interrupt
     with `value` as the return of interrupt(), then continues until the
     next interrupt or END.
"""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.core.brain.schemas import WorkflowState
from app.domains.fyp.workflows.discovery import build_discovery_graph
from app.domains.fyp.workflows.discovery.taxonomy import INDUSTRIES


def _config(thread_id: str) -> dict:
    """Helper: build a LangGraph config with a unique thread_id."""
    return {"configurable": {"thread_id": thread_id}}


def _initial_state(workspace_id: str) -> dict:
    """Helper: the starting state for a new Discovery workflow run."""
    return {
        "workspace_id": workspace_id,
        "workflow_state": WorkflowState.INDUSTRY_SELECTION.value,
        "industry": None,
        "branch": None,
    }


# ── Graph compilation ─────────────────────────────────────────────────────────

def test_graph_compiles():
    """The graph can be built and compiled without errors."""
    graph = build_discovery_graph(MemorySaver())
    assert graph is not None


def test_graph_has_correct_nodes():
    """The graph contains the three expected node names."""
    graph = build_discovery_graph(MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())
    assert "industry_selection" in node_names
    assert "branch_selection" in node_names
    assert "evidence_research" in node_names


# ── Industry selection ────────────────────────────────────────────────────────

async def test_graph_pauses_at_industry_selection():
    """
    When started, the graph immediately pauses at industry_selection
    and waits for the student to pick an industry.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-pause-industry")

    await graph.ainvoke(_initial_state("ws-pause-industry"), config=config)

    state = graph.get_state(config)
    # next tells us which node the graph is waiting to run
    assert "industry_selection" in state.next


async def test_interrupt_payload_contains_industries():
    """
    The interrupt raised inside industry_selection_node
    includes the list of available industries.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-payload-industry")

    await graph.ainvoke(_initial_state("ws-payload-industry"), config=config)

    state = graph.get_state(config)
    interrupts = state.tasks[0].interrupts
    assert len(interrupts) > 0

    payload = interrupts[0].value
    assert "available_industries" in payload
    assert "Defense" in payload["available_industries"]
    assert payload["stage"] == WorkflowState.INDUSTRY_SELECTION.value


async def test_selecting_industry_updates_state():
    """
    After resuming with a valid industry, the state reflects the choice
    and the workflow moves to BRANCH_SELECTION.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-select-industry")

    await graph.ainvoke(_initial_state("ws-select-industry"), config=config)
    result = await graph.ainvoke(Command(resume="Defense"), config=config)

    assert result["industry"] == "Defense"
    assert result["workflow_state"] == WorkflowState.BRANCH_SELECTION.value


async def test_invalid_industry_raises_value_error():
    """
    Resuming with an industry that is not in the taxonomy
    raises a ValueError inside the node.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-invalid-industry")

    await graph.ainvoke(_initial_state("ws-invalid-industry"), config=config)

    with pytest.raises(Exception):
        await graph.ainvoke(Command(resume="Underwater Basket Weaving"), config=config)


# ── Branch selection ──────────────────────────────────────────────────────────

async def test_graph_pauses_at_branch_selection():
    """After industry is chosen, the graph pauses at branch_selection."""
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-pause-branch")

    await graph.ainvoke(_initial_state("ws-pause-branch"), config=config)
    await graph.ainvoke(Command(resume="Healthcare"), config=config)

    state = graph.get_state(config)
    assert "branch_selection" in state.next


async def test_interrupt_payload_contains_branches_for_industry():
    """
    The branch_selection interrupt includes only branches relevant
    to the previously selected industry.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-payload-branch")

    await graph.ainvoke(_initial_state("ws-payload-branch"), config=config)
    await graph.ainvoke(Command(resume="Defense"), config=config)

    state = graph.get_state(config)
    interrupts = state.tasks[0].interrupts
    payload = interrupts[0].value

    assert "available_branches" in payload
    assert "Navy" in payload["available_branches"]
    assert payload["industry"] == "Defense"
    assert payload["stage"] == WorkflowState.BRANCH_SELECTION.value


async def test_selecting_branch_updates_state():
    """
    After resuming with a valid branch, the state reflects the choice
    and the workflow moves to EVIDENCE_RESEARCH.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-select-branch")

    await graph.ainvoke(_initial_state("ws-select-branch"), config=config)
    await graph.ainvoke(Command(resume="Defense"), config=config)
    result = await graph.ainvoke(Command(resume="Navy"), config=config)

    assert result["branch"] == "Navy"
    assert result["workflow_state"] == WorkflowState.EVIDENCE_RESEARCH.value


async def test_invalid_branch_raises_value_error():
    """
    Resuming with a branch that doesn't belong to the selected industry
    raises a ValueError inside the node.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-invalid-branch")

    await graph.ainvoke(_initial_state("ws-invalid-branch"), config=config)
    await graph.ainvoke(Command(resume="Defense"), config=config)

    with pytest.raises(Exception):
        await graph.ainvoke(Command(resume="Clinical AI"), config=config)  # Healthcare branch, not Defense


# ── Full end-to-end Release 0.1 journey ──────────────────────────────────────

async def test_full_release_01_journey():
    """
    Complete Release 0.1 flow through the Discovery workflow:
    start → select industry → select branch → reach EVIDENCE_RESEARCH.
    """
    graph = build_discovery_graph(MemorySaver())
    config = _config("test-full-journey")

    # 1. Start the project — graph pauses at industry selection
    await graph.ainvoke(_initial_state("ws-full-journey"), config=config)
    state = graph.get_state(config)
    assert "industry_selection" in state.next

    # 2. Student selects industry — graph pauses at branch selection
    result = await graph.ainvoke(Command(resume="Healthcare"), config=config)
    assert result["industry"] == "Healthcare"
    assert result["workflow_state"] == WorkflowState.BRANCH_SELECTION.value

    # 3. Student selects branch — workflow reaches EVIDENCE_RESEARCH
    result = await graph.ainvoke(Command(resume="Medical Imaging"), config=config)
    assert result["branch"] == "Medical Imaging"
    assert result["workflow_state"] == WorkflowState.EVIDENCE_RESEARCH.value

    # 4. Release 0.2: the graph pauses just before research instead of ending,
    #    so research can run as its own streamed step (see test_research_workflow.py).
    final_state = graph.get_state(config)
    assert final_state.next == ("evidence_research",)


async def test_different_workspace_ids_are_isolated():
    """
    Two concurrent projects do not interfere with each other.
    Each workspace_id (thread_id) gets its own independent state.
    """
    graph = build_discovery_graph(MemorySaver())
    config_a = _config("thread-a")
    config_b = _config("thread-b")

    # Start both projects
    await graph.ainvoke(_initial_state("ws-a"), config=config_a)
    await graph.ainvoke(_initial_state("ws-b"), config=config_b)

    # Advance project A to branch selection with Defense
    await graph.ainvoke(Command(resume="Defense"), config=config_a)

    # Advance project B to branch selection with Healthcare
    await graph.ainvoke(Command(resume="Healthcare"), config=config_b)

    # Complete project A
    result_a = await graph.ainvoke(Command(resume="Navy"), config=config_a)

    # Complete project B
    result_b = await graph.ainvoke(Command(resume="Clinical AI"), config=config_b)

    # Each project has its own correct state
    assert result_a["industry"] == "Defense"
    assert result_a["branch"] == "Navy"
    assert result_b["industry"] == "Healthcare"
    assert result_b["branch"] == "Clinical AI"
