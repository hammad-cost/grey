"""
Model Selection workflow graph (Release 0.9).

    START
      ↓
    find_models     ← find_models skill: search, choose 0-3 options (or "no model needed")
      ↓
    model_review    ← HITL interrupt: approve, or look for other models
      ↓ approve            ↓ research (up to 2 times)
    END              back to find_models

Compiled with a MemorySaver checkpointer (thread_id = workspace_id). The
runner rebuilds the paused position from the Project Brain, so restarts are safe.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.model_selection.nodes import after_review, make_find_models_node, model_review_node
from app.domains.fyp.workflows.model_selection.state import ModelSelectionState

FIND_MODELS_NODE = "find_models"
MODEL_REVIEW_NODE = "model_review"


def build_model_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """Build and compile the Model Selection workflow graph."""
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(ModelSelectionState)

    builder.add_node(FIND_MODELS_NODE, make_find_models_node(registry))
    builder.add_node(MODEL_REVIEW_NODE, model_review_node)

    builder.set_entry_point(FIND_MODELS_NODE)
    builder.add_edge(FIND_MODELS_NODE, MODEL_REVIEW_NODE)
    builder.add_conditional_edges(MODEL_REVIEW_NODE, after_review, {"approved": END, "research": FIND_MODELS_NODE})

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
model_graph = build_model_graph()
