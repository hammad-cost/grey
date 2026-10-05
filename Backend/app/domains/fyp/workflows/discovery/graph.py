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
      ⏸  pause before research (so picking a branch returns immediately)
      ↓
    evidence_research   ← runs the Evidence Research skill (Release 0.2)
      ↓
    END                 ← Release 0.2 stops here; problem extraction comes later

How it works:
  - The graph is compiled with a MemorySaver checkpointer.
  - Each project gets a unique thread_id (= workspace_id) so separate
    students do not interfere with each other.
  - When the graph hits interrupt(), it pauses. The API layer calls
    graph.ainvoke(Command(resume=<selection>), config=...) to continue.
  - The graph also pauses *before* evidence_research (interrupt_before).
    This is not a student decision — it lets research run as its own,
    streamed step (see research_runner.py) instead of inside the branch request.
  - The durable Project Brain (database) is updated by the API layer and
    the research runner, not by the graph itself.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.discovery.nodes import (
    branch_selection_node,
    industry_selection_node,
    make_evidence_research_node,
)
from app.domains.fyp.workflows.discovery.state import DiscoveryState

# Node names used outside this file (e.g. by the research runner).
BRANCH_SELECTION_NODE = "branch_selection"
EVIDENCE_RESEARCH_NODE = "evidence_research"


def build_discovery_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """
    Build and compile the Discovery workflow graph.

    Args:
        checkpointer: A LangGraph checkpointer that persists graph state
                      between API calls. Defaults to MemorySaver (in-memory).
                      Pass a fresh MemorySaver() in tests to keep them isolated.
        skills:       Where nodes look up skills by name. Defaults to the
                      application's shared skill_registry. Tests pass their own
                      registry (e.g. with a fake search provider).

    Returns:
        A compiled LangGraph graph ready to invoke.
    """
    builder = StateGraph(DiscoveryState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    builder.add_node("industry_selection", industry_selection_node)
    builder.add_node(BRANCH_SELECTION_NODE, branch_selection_node)
    builder.add_node(
        EVIDENCE_RESEARCH_NODE,
        make_evidence_research_node(skills if skills is not None else skill_registry),
    )

    # ── Edges ─────────────────────────────────────────────────────────────────
    # Entry point: the graph always starts at industry selection.
    builder.set_entry_point("industry_selection")

    # Linear transitions — no branching or conditions needed yet.
    builder.add_edge("industry_selection", BRANCH_SELECTION_NODE)
    builder.add_edge(BRANCH_SELECTION_NODE, EVIDENCE_RESEARCH_NODE)
    builder.add_edge(EVIDENCE_RESEARCH_NODE, END)

    return builder.compile(
        checkpointer=checkpointer or MemorySaver(),
        interrupt_before=[EVIDENCE_RESEARCH_NODE],
    )


# Shared graph instance used by the API.
# Each project uses its own thread_id so state is isolated per student.
discovery_graph = build_discovery_graph()
