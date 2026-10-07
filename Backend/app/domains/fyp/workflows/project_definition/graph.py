"""
Project Definition workflow graph (Release 0.6) — its own workflow, like
Discovery and FYP Design (one workflow per stage of the journey).

    START
      ↓
    define_project   ← define_project skill: problem definition, scope, solution
      ↓
    scope_review     ← HITL interrupt: move a feature, or approve the scope
      ↓ approve          ↺ move (back to scope_review)
    END

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
from app.domains.fyp.workflows.project_definition.nodes import (
    after_review,
    make_define_project_node,
    scope_review_node,
)
from app.domains.fyp.workflows.project_definition.state import ProjectDefinitionState

# Node names used outside this file (by the runner).
DEFINE_PROJECT_NODE = "define_project"
SCOPE_REVIEW_NODE = "scope_review"


def build_project_definition_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """
    Build and compile the Project Definition workflow graph.

    Args:
        checkpointer: defaults to MemorySaver (in-memory). Tests pass a fresh one.
        skills:       where nodes look up skills by name. Defaults to the shared
                      skill_registry; tests pass their own (with a fake LLM).
    """
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(ProjectDefinitionState)

    builder.add_node(DEFINE_PROJECT_NODE, make_define_project_node(registry))
    builder.add_node(SCOPE_REVIEW_NODE, scope_review_node)

    builder.set_entry_point(DEFINE_PROJECT_NODE)
    builder.add_edge(DEFINE_PROJECT_NODE, SCOPE_REVIEW_NODE)
    builder.add_conditional_edges(SCOPE_REVIEW_NODE, after_review, {"approved": END, "review": SCOPE_REVIEW_NODE})

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
project_definition_graph = build_project_definition_graph()
