"""
Technical Plan workflow graph (Release 0.11).

    START → design_architecture → architecture_review (HITL interrupt)
                                     ↓ approve → END
                                     ↓ redesign (≤2, "simpler") → design_architecture

MemorySaver checkpointer (thread_id = workspace_id); restart-safe via the runner.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.technical_plan.nodes import (
    after_review,
    architecture_review_node,
    make_design_architecture_node,
)
from app.domains.fyp.workflows.technical_plan.state import TechnicalPlanState

DESIGN_ARCHITECTURE_NODE = "design_architecture"
ARCHITECTURE_REVIEW_NODE = "architecture_review"


def build_technical_plan_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """Build and compile the Technical Plan workflow graph."""
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(TechnicalPlanState)
    builder.add_node(DESIGN_ARCHITECTURE_NODE, make_design_architecture_node(registry))
    builder.add_node(ARCHITECTURE_REVIEW_NODE, architecture_review_node)
    builder.set_entry_point(DESIGN_ARCHITECTURE_NODE)
    builder.add_edge(DESIGN_ARCHITECTURE_NODE, ARCHITECTURE_REVIEW_NODE)
    builder.add_conditional_edges(
        ARCHITECTURE_REVIEW_NODE, after_review, {"approved": END, "redesign": DESIGN_ARCHITECTURE_NODE}
    )
    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
technical_plan_graph = build_technical_plan_graph()
