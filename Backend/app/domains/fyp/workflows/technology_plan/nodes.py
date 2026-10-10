"""
Technology Plan workflow nodes (Release 0.10). Nodes never touch the database;
the skill comes from the Skill Registry; the approval is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import (
    MAX_TECHNOLOGY_REPLANS,
    AIStrategy,
    DatasetOption,
    FunctionalArea,
    FYPDesign,
    ModelPlan,
    ProjectDefinition,
    TechnologyPlan,
    TechnologyPreference,
    WorkflowState,
)
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.skills.plan_technology import PlanTechnologyInput, TechnologyProgress
from app.domains.fyp.workflows.technology_plan.state import TechnologyPlanState

PLAN_SKILL_NAME = "plan_technology"
TECHNOLOGY_PROGRESS_KIND = "technology_progress"

APPROVE = "approve"
REPLAN = "replan"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: TechnologyProgress) -> None:
        write({"kind": TECHNOLOGY_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_plan_technology_node(skills: SkillRegistry):
    """Build the plan_technology node: one choice per needed stack area, and the hardware (blueprint §27–29)."""

    async def plan_technology_node(state: TechnologyPlanState) -> dict:
        preference = state.get("preference")
        previous = state.get("plan")
        output = await skills.get(PLAN_SKILL_NAME).execute(
            PlanTechnologyInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                area=FunctionalArea.model_validate(state["area"]),
                problem=ProblemBrief.model_validate(state["problem"]),
                design=FYPDesign.model_validate(state["design"]),
                definition=ProjectDefinition.model_validate(state["definition"]),
                strategy=AIStrategy.model_validate(state["strategy"]),
                dataset=DatasetOption.model_validate(state["dataset"]),
                models=ModelPlan.model_validate(state["models"]),
                preference=TechnologyPreference(preference) if preference else None,
                previous_plan=TechnologyPlan.model_validate(previous) if preference and previous else None,
            ),
            on_progress=_forwarder(),
        )
        return {
            "plan_output": output.model_dump(mode="json"),
            "plan": output.plan.model_dump(mode="json"),
            "plan_id": state.get("plan_id") or str(uuid.uuid4()),
            "replans_used": state.get("replans_used", 0) + (1 if preference else 0),
            "preference": None,
            "workflow_state": WorkflowState.TECHNOLOGY_PLAN.value,
        }

    return plan_technology_node


def technology_review_node(state: TechnologyPlanState) -> dict:
    """
    Pause until the student approves the plan or asks for a simpler one (mandatory HITL).
    Resumed with Command(resume={"action": "approve", "plan_id": …}) or
    Command(resume={"action": "replan", "preference": "simpler"}).
    """
    used = state.get("replans_used", 0)
    decision = interrupt({
        "stage": WorkflowState.TECHNOLOGY_PLAN.value,
        "plan_id": state.get("plan_id"),
        "replans_left": max(0, MAX_TECHNOLOGY_REPLANS - used),
        "prompt": "Approve the technology plan, or ask Grey for a simpler one.",
    })
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == APPROVE:
        if decision.get("plan_id") != state.get("plan_id"):
            raise ValueError("Only this project's technology plan can be approved.")
        return {"approved_plan_id": state["plan_id"], "workflow_state": WorkflowState.TECHNOLOGY_APPROVED.value}
    if action == REPLAN:
        if used >= MAX_TECHNOLOGY_REPLANS:
            raise ValueError(f"All {MAX_TECHNOLOGY_REPLANS} re-plans have been used.")
        return {"preference": TechnologyPreference(decision.get("preference")).value}
    raise ValueError(f"Unknown technology review action: {action!r}.")


def after_review(state: TechnologyPlanState) -> str:
    return "approved" if state.get("approved_plan_id") else "replan"
