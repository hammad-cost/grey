"""
Technical Plan workflow nodes (Release 0.11). Nodes never touch the database;
the skill comes from the Skill Registry; the approval is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import (
    MAX_ARCHITECTURE_REDESIGNS,
    AIStrategy,
    ArchitecturePreference,
    DatasetOption,
    FYPDesign,
    ModelPlan,
    ProjectDefinition,
    TechnicalPlan,
    TechnologyPlan,
    WorkflowState,
)
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.design_architecture import ArchitectureProgress, DesignArchitectureInput
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.workflows.technical_plan.state import TechnicalPlanState

DESIGN_SKILL_NAME = "design_architecture"
ARCHITECTURE_PROGRESS_KIND = "architecture_progress"

APPROVE = "approve"
REDESIGN = "redesign"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: ArchitectureProgress) -> None:
        write({"kind": ARCHITECTURE_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_design_architecture_node(skills: SkillRegistry):
    """Build the design_architecture node: the architecture and evaluation plan (blueprint §30–31)."""

    async def design_architecture_node(state: TechnicalPlanState) -> dict:
        preference = state.get("preference")
        previous = state.get("plan")
        output = await skills.get(DESIGN_SKILL_NAME).execute(
            DesignArchitectureInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                problem=ProblemBrief.model_validate(state["problem"]),
                design=FYPDesign.model_validate(state["design"]),
                definition=ProjectDefinition.model_validate(state["definition"]),
                strategy=AIStrategy.model_validate(state["strategy"]),
                dataset=DatasetOption.model_validate(state["dataset"]),
                models=ModelPlan.model_validate(state["models"]),
                technology=TechnologyPlan.model_validate(state["technology"]),
                preference=ArchitecturePreference(preference) if preference else None,
                previous_plan=TechnicalPlan.model_validate(previous) if preference and previous else None,
            ),
            on_progress=_forwarder(),
        )
        return {
            "plan_output": output.model_dump(mode="json"),
            "plan": output.plan.model_dump(mode="json"),
            "plan_id": state.get("plan_id") or str(uuid.uuid4()),
            "redesigns_used": state.get("redesigns_used", 0) + (1 if preference else 0),
            "preference": None,
            "workflow_state": WorkflowState.ARCHITECTURE.value,
        }

    return design_architecture_node


def architecture_review_node(state: TechnicalPlanState) -> dict:
    """
    Pause until the student approves the technical plan or asks for a simpler one (mandatory HITL).
    Resumed with Command(resume={"action": "approve", "plan_id": …}) or
    Command(resume={"action": "redesign", "preference": "simpler"}).
    """
    used = state.get("redesigns_used", 0)
    decision = interrupt({
        "stage": WorkflowState.ARCHITECTURE.value,
        "plan_id": state.get("plan_id"),
        "redesigns_left": max(0, MAX_ARCHITECTURE_REDESIGNS - used),
        "prompt": "Approve the architecture and evaluation plan, or ask Grey for a simpler architecture.",
    })
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == APPROVE:
        if decision.get("plan_id") != state.get("plan_id"):
            raise ValueError("Only this project's technical plan can be approved.")
        return {"approved_plan_id": state["plan_id"], "workflow_state": WorkflowState.TECHNICAL_PLAN_APPROVED.value}
    if action == REDESIGN:
        if used >= MAX_ARCHITECTURE_REDESIGNS:
            raise ValueError(f"All {MAX_ARCHITECTURE_REDESIGNS} redesigns have been used.")
        return {"preference": ArchitecturePreference(decision.get("preference")).value}
    raise ValueError(f"Unknown architecture review action: {action!r}.")


def after_review(state: TechnicalPlanState) -> str:
    return "approved" if state.get("approved_plan_id") else "redesign"
