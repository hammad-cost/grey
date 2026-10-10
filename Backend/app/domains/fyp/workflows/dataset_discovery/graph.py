"""
Dataset Discovery workflow graph (Release 0.8) — its own workflow, like the
earlier stages (one workflow per stage of the journey).

    START
      ↓
    find_datasets    ← find_datasets skill: search dataset sites, recommend a primary + an alternative
      ↓
    dataset_review   ← HITL interrupt: select one of the two, or search again with a preference
      ↓ select              ↓ research (up to 2 times)
    END               back to find_datasets

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
from app.domains.fyp.workflows.dataset_discovery.nodes import (
    after_review,
    dataset_review_node,
    make_find_datasets_node,
)
from app.domains.fyp.workflows.dataset_discovery.state import DatasetDiscoveryState

# Node names used outside this file (by the runner).
FIND_DATASETS_NODE = "find_datasets"
DATASET_REVIEW_NODE = "dataset_review"


def build_dataset_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """
    Build and compile the Dataset Discovery workflow graph.

    Args:
        checkpointer: defaults to MemorySaver (in-memory). Tests pass a fresh one.
        skills:       where nodes look up skills by name. Defaults to the shared
                      skill_registry; tests pass their own (with a fake LLM and mock search).
    """
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(DatasetDiscoveryState)

    builder.add_node(FIND_DATASETS_NODE, make_find_datasets_node(registry))
    builder.add_node(DATASET_REVIEW_NODE, dataset_review_node)

    builder.set_entry_point(FIND_DATASETS_NODE)
    builder.add_edge(FIND_DATASETS_NODE, DATASET_REVIEW_NODE)
    builder.add_conditional_edges(
        DATASET_REVIEW_NODE, after_review, {"selected": END, "research": FIND_DATASETS_NODE}
    )

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
dataset_graph = build_dataset_graph()
