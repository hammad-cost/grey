"""
FYP Design workflow graph (Release 0.5) — separate from Discovery, as the
backend blueprint asks (one workflow per stage of the journey).

    START
      ↓
    area_classification  ← classify_area skill: where the problem sits
      ↓
    fyp_design           ← design_fyp skill: a student-sized FYP
      ↓
    fyp_review           ← HITL interrupt: approve, or one controlled redesign
      ↓ approve                 ↓ adjust (up to 3 times)
    END                  back to fyp_design

How it works:
  - Compiled with a MemorySaver checkpointer; each project uses its
    workspace_id as the thread_id (this graph has its own checkpointer).
  - The paused workflow lives in memory. The runner rebuilds its position
    from the Project Brain before every step, so restarts are safe.
  - The graph never saves anything; the runner writes to the Project Brain.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.fyp_design.nodes import (
    after_review,
    fyp_review_node,
    make_area_classification_node,
    make_fyp_design_node,
)
from app.domains.fyp.workflows.fyp_design.state import FYPDesignState

# Node names used outside this file (by the runner).
AREA_CLASSIFICATION_NODE = "area_classification"
FYP_DESIGN_NODE = "fyp_design"
FYP_REVIEW_NODE = "fyp_review"


def build_fyp_design_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """
    Build and compile the FYP Design workflow graph.

    Args:
        checkpointer: defaults to MemorySaver (in-memory). Tests pass a fresh one.
        skills:       where nodes look up skills by name. Defaults to the shared
                      skill_registry; tests pass their own (with a fake LLM).
    """
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(FYPDesignState)

    builder.add_node(AREA_CLASSIFICATION_NODE, make_area_classification_node(registry))
    builder.add_node(FYP_DESIGN_NODE, make_fyp_design_node(registry))
    builder.add_node(FYP_REVIEW_NODE, fyp_review_node)

    builder.set_entry_point(AREA_CLASSIFICATION_NODE)
    builder.add_edge(AREA_CLASSIFICATION_NODE, FYP_DESIGN_NODE)
    builder.add_edge(FYP_DESIGN_NODE, FYP_REVIEW_NODE)
    builder.add_conditional_edges(FYP_REVIEW_NODE, after_review, {"approved": END, "redesign": FYP_DESIGN_NODE})

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
fyp_design_graph = build_fyp_design_graph()
