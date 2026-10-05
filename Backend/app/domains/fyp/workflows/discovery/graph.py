"""
Discovery workflow graph.

Assembles the LangGraph StateGraph for the FYP Discovery workflow.
This is the state machine that controls the journey:

    START
      ↓
    industry_selection  ← HITL interrupt (student picks industry)
      ↓
    branch_selection    ← HITL interrupt (student picks branch)
      ↓
    evidence_research   ← Release 0.1 stops here
      ↓
    END

How it works:
  - The graph is compiled with a MemorySaver checkpointer.
  - Each project gets a unique thread_id (= workspace_id) so separate
    students do not interfere with each other.
  - When the graph hits interrupt(), it pauses. The API layer calls
    graph.ainvoke(Command(resume=<selection>), config=...) to continue.
  - The durable Project Brain (database) is updated by the API layer,
    not by the graph itself.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.domains.fyp.workflows.discovery.nodes import (
    branch_selection_node,
    evidence_research_node,
    industry_selection_node,
)
from app.domains.fyp.workflows.discovery.state import DiscoveryState


def build_discovery_graph(checkpointer=None):
    """
    Build and compile the Discovery workflow graph.

    Args:
        checkpointer: A LangGraph checkpointer that persists graph state
                      between API calls. Defaults to MemorySaver (in-memory).
                      Pass a fresh MemorySaver() in tests to keep them isolated.

    Returns:
        A compiled LangGraph graph ready to invoke.
    """
    builder = StateGraph(DiscoveryState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    builder.add_node("industry_selection", industry_selection_node)
    builder.add_node("branch_selection", branch_selection_node)
    builder.add_node("evidence_research", evidence_research_node)

    # ── Edges ─────────────────────────────────────────────────────────────────
    # Entry point: the graph always starts at industry selection.
    builder.set_entry_point("industry_selection")

    # Linear transitions — no branching or conditions needed in Release 0.1.
    builder.add_edge("industry_selection", "branch_selection")
    builder.add_edge("branch_selection", "evidence_research")
    builder.add_edge("evidence_research", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
# Each project uses its own thread_id so state is isolated per student.
discovery_graph = build_discovery_graph()
