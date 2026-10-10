"""
Supervisor Readiness workflow graph (Release 0.13).

    START → prepare_brief → readiness_review (HITL interrupt: confirm) → END

MemorySaver checkpointer (thread_id = workspace_id); restart-safe via the runner.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.supervisor_readiness.nodes import make_prepare_brief_node, readiness_review_node
from app.domains.fyp.workflows.supervisor_readiness.state import SupervisorReadinessState

PREPARE_BRIEF_NODE = "prepare_brief"
READINESS_REVIEW_NODE = "readiness_review"


def build_supervisor_readiness_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """Build and compile the Supervisor Readiness workflow graph."""
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(SupervisorReadinessState)
    builder.add_node(PREPARE_BRIEF_NODE, make_prepare_brief_node(registry))
    builder.add_node(READINESS_REVIEW_NODE, readiness_review_node)
    builder.set_entry_point(PREPARE_BRIEF_NODE)
    builder.add_edge(PREPARE_BRIEF_NODE, READINESS_REVIEW_NODE)
    builder.add_edge(READINESS_REVIEW_NODE, END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
supervisor_readiness_graph = build_supervisor_readiness_graph()
