"""
Proposal workflow graph (Release 0.14) — the last stage of the FYP journey.

    START → generate_proposal → proposal_review (HITL interrupt)
                                   ↓ finalize → END  (stage COMPLETE)
                                   ↓ rewrite one section (≤3) → generate_proposal

MemorySaver checkpointer (thread_id = workspace_id); restart-safe via the runner.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.skills.registry import SkillRegistry, skill_registry
from app.domains.fyp.workflows.proposal.nodes import after_review, make_generate_proposal_node, proposal_review_node
from app.domains.fyp.workflows.proposal.state import ProposalState

GENERATE_PROPOSAL_NODE = "generate_proposal"
PROPOSAL_REVIEW_NODE = "proposal_review"


def build_proposal_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """Build and compile the Proposal workflow graph."""
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(ProposalState)
    builder.add_node(GENERATE_PROPOSAL_NODE, make_generate_proposal_node(registry))
    builder.add_node(PROPOSAL_REVIEW_NODE, proposal_review_node)
    builder.set_entry_point(GENERATE_PROPOSAL_NODE)
    builder.add_edge(GENERATE_PROPOSAL_NODE, PROPOSAL_REVIEW_NODE)
    builder.add_conditional_edges(PROPOSAL_REVIEW_NODE, after_review, {"finalized": END, "rewrite": GENERATE_PROPOSAL_NODE})
    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
proposal_graph = build_proposal_graph()
