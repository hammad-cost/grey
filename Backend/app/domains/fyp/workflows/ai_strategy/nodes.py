"""
AI Strategy workflow nodes (Release 0.7).

Rules (same as the other workflows):
  - Nodes never touch the database — the runner saves results to the Brain.
  - Skills are looked up by name in the Skill Registry, never created here.
  - Nodes forward only safe progress (step labels), never model reasoning.
  - The student's review is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.ai_strategy_rules import recheck_problem
from app.core.brain.schemas import (
    MAX_AI_STRATEGY_RECHECKS,
    AIStrategy,
    AIStrategyPreference,
    FunctionalArea,
    FYPDesign,
    ProjectDefinition,
    WorkflowState,
)
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.skills.plan_ai_strategy import AIStrategyProgress, PlanAIStrategyInput
from app.domains.fyp.workflows.ai_strategy.state import AIStrategyState

# Name the skill is registered under in the Skill Registry.
PLAN_SKILL_NAME = "plan_ai_strategy"

# Marks a progress update on LangGraph's custom stream.
AI_STRATEGY_PROGRESS_KIND = "ai_strategy_progress"

APPROVE = "approve"
RECHECK = "recheck"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: AIStrategyProgress) -> None:
        write({"kind": AI_STRATEGY_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_plan_ai_strategy_node(skills: SkillRegistry):
    """
    Build the plan_ai_strategy node: check whether the project needs AI and,
    if it does, plan the AI task and approach (blueprint §22–23). On a re-check
    the skill also gets the student's preference and the previous answer.
    The strategy keeps one id; the runner saves it to the Brain with that id.
    """

    async def plan_ai_strategy_node(state: AIStrategyState) -> dict:
        preference = state.get("preference")
        previous = state.get("strategy")
        output = await skills.get(PLAN_SKILL_NAME).execute(
            PlanAIStrategyInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                area=FunctionalArea.model_validate(state["area"]),
                problem=ProblemBrief.model_validate(state["problem"]),
                design=FYPDesign.model_validate(state["design"]),
                definition=ProjectDefinition.model_validate(state["definition"]),
                preference=AIStrategyPreference(preference) if preference else None,
                previous_strategy=AIStrategy.model_validate(previous) if preference and previous else None,
            ),
            on_progress=_forwarder(),
        )
        return {
            "strategy_output": output.model_dump(mode="json"),
            "strategy": output.strategy.model_dump(mode="json"),
            "strategy_id": state.get("strategy_id") or str(uuid.uuid4()),
            "rechecks_used": state.get("rechecks_used", 0) + (1 if preference else 0),
            "preference": None,
            "workflow_state": WorkflowState.AI_STRATEGY.value,
        }

    return plan_ai_strategy_node


def strategy_review_node(state: AIStrategyState) -> dict:
    """
    Pause until the student approves the AI strategy or asks Grey to check
    again with a preference (mandatory HITL). The API resumes the graph with
    Command(resume={"action": "approve", "strategy_id": …}) or
    Command(resume={"action": "recheck", "preference": "without_ai" | "existing_model"}).
    A re-check goes back to plan_ai_strategy; approval ends the workflow.
    """
    used = state.get("rechecks_used", 0)
    decision = interrupt({
        "stage": WorkflowState.AI_STRATEGY.value,
        "strategy_id": state.get("strategy_id"),
        "rechecks_left": max(0, MAX_AI_STRATEGY_RECHECKS - used),
        "prompt": "Approve the AI strategy, or ask Grey to check again with a preference.",
    })

    action = decision.get("action") if isinstance(decision, dict) else None
    if action == APPROVE:
        if decision.get("strategy_id") != state.get("strategy_id"):
            raise ValueError("Only this project's AI strategy can be approved.")
        return {
            "approved_strategy_id": state["strategy_id"],
            "workflow_state": WorkflowState.AI_STRATEGY_APPROVED.value,
        }
    if action == RECHECK:
        if used >= MAX_AI_STRATEGY_RECHECKS:
            raise ValueError(f"All {MAX_AI_STRATEGY_RECHECKS} re-checks have been used.")
        preference = AIStrategyPreference(decision.get("preference"))
        problem = recheck_problem(AIStrategy.model_validate(state["strategy"]), preference)
        if problem is not None:
            raise ValueError(problem)
        return {"preference": preference.value}
    raise ValueError(f"Unknown AI strategy review action: {action!r}.")


def after_review(state: AIStrategyState) -> str:
    """Approved → the workflow ends. Otherwise (a re-check) → back to plan_ai_strategy."""
    return "approved" if state.get("approved_strategy_id") else "recheck"
