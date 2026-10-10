"""
AI Strategy workflow graph (Release 0.7) — its own workflow, like Discovery,
FYP Design and Project Definition (one workflow per stage of the journey).

    START
      ↓
    plan_ai_strategy   ← plan_ai_strategy skill: does the project need AI? which task and approach?
      ↓
    strategy_review    ← HITL interrupt: approve, or check again with a preference
      ↓ approve              ↓ recheck (up to 2 times)
    END                back to plan_ai_strategy

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
from app.domains.fyp.workflows.ai_strategy.nodes import (
    after_review,
    make_plan_ai_strategy_node,
    strategy_review_node,
)
from app.domains.fyp.workflows.ai_strategy.state import AIStrategyState

# Node names used outside this file (by the runner).
PLAN_AI_STRATEGY_NODE = "plan_ai_strategy"
STRATEGY_REVIEW_NODE = "strategy_review"


def build_ai_strategy_graph(checkpointer=None, skills: SkillRegistry | None = None):
    """
    Build and compile the AI Strategy workflow graph.

    Args:
        checkpointer: defaults to MemorySaver (in-memory). Tests pass a fresh one.
        skills:       where nodes look up skills by name. Defaults to the shared
                      skill_registry; tests pass their own (with a fake LLM).
    """
    registry = skills if skills is not None else skill_registry
    builder = StateGraph(AIStrategyState)

    builder.add_node(PLAN_AI_STRATEGY_NODE, make_plan_ai_strategy_node(registry))
    builder.add_node(STRATEGY_REVIEW_NODE, strategy_review_node)

    builder.set_entry_point(PLAN_AI_STRATEGY_NODE)
    builder.add_edge(PLAN_AI_STRATEGY_NODE, STRATEGY_REVIEW_NODE)
    builder.add_conditional_edges(
        STRATEGY_REVIEW_NODE, after_review, {"approved": END, "recheck": PLAN_AI_STRATEGY_NODE}
    )

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Shared graph instance used by the API.
ai_strategy_graph = build_ai_strategy_graph()
