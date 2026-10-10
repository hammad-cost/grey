"""
Technology Plan workflow graph (Release 0.10).

    START → plan_technology → technology_review (HITL interrupt)
                                  ↓ approve → END
                                  ↓ replan (≤2, "simpler / cheaper") → plan_technology

MemorySaver checkpointer (thread_id = workspace_id); the runner rebuilds the
paused position from the Project Brain, so restarts are safe.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.technology_plan.nodes import (
    after_review,
    make_plan_technology_node,
    technology_review_node,
)
from app.domains.fyp.workflows.technology_plan.state import TechnologyPlanState

PLAN_TECHNOLOGY_NODE = "plan_technology"
TECHNOLOGY_REVIEW_NODE = "technology_review"


def build_technology_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """Build and compile the Technology Plan workflow graph."""
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(TechnologyPlanState)
    builder.add_node(PLAN_TECHNOLOGY_NODE, make_plan_technology_node(registry))
    builder.add_node(TECHNOLOGY_REVIEW_NODE, technology_review_node)
    builder.set_entry_point(PLAN_TECHNOLOGY_NODE)
    builder.add_edge(PLAN_TECHNOLOGY_NODE, TECHNOLOGY_REVIEW_NODE)
    builder.add_conditional_edges(TECHNOLOGY_REVIEW_NODE, after_review, {"approved": END, "replan": PLAN_TECHNOLOGY_NODE})
    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
technology_graph = build_technology_graph()
