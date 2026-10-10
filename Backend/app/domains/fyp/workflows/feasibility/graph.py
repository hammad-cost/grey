"""
Feasibility workflow graph (Release 0.12).

    START → assess_feasibility → feasibility_review (HITL interrupt: accept) → END

There is no re-assessment: the report is an analysis of decisions the student
already approved. MemorySaver checkpointer (thread_id = workspace_id).
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.feasibility.nodes import feasibility_review_node, make_assess_feasibility_node
from app.domains.fyp.workflows.feasibility.state import FeasibilityState

ASSESS_FEASIBILITY_NODE = "assess_feasibility"
FEASIBILITY_REVIEW_NODE = "feasibility_review"


def build_feasibility_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """Build and compile the Feasibility workflow graph."""
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(FeasibilityState)
    builder.add_node(ASSESS_FEASIBILITY_NODE, make_assess_feasibility_node(registry))
    builder.add_node(FEASIBILITY_REVIEW_NODE, feasibility_review_node)
    builder.set_entry_point(ASSESS_FEASIBILITY_NODE)
    builder.add_edge(ASSESS_FEASIBILITY_NODE, FEASIBILITY_REVIEW_NODE)
    builder.add_edge(FEASIBILITY_REVIEW_NODE, END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
feasibility_graph = build_feasibility_graph()
