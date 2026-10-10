"""
Feasibility workflow nodes (Release 0.12). Nodes never touch the database; the
skill comes from the Skill Registry; acceptance is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import (
    AIStrategy,
    DatasetOption,
    EvidenceTier,
    FYPDesign,
    ModelPlan,
    ProjectDefinition,
    TechnicalPlan,
    TechnologyPlan,
    WorkflowState,
)
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.assess_feasibility import AssessFeasibilityInput, FeasibilityProgress
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.workflows.feasibility.state import FeasibilityState

ASSESS_SKILL_NAME = "assess_feasibility"
FEASIBILITY_PROGRESS_KIND = "feasibility_progress"
ACCEPT = "accept"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: FeasibilityProgress) -> None:
        write({"kind": FEASIBILITY_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_assess_feasibility_node(skills: SkillRegistry):
    """Build the assess_feasibility node (blueprint §32)."""

    async def assess_feasibility_node(state: FeasibilityState) -> dict:
        output = await skills.get(ASSESS_SKILL_NAME).execute(
            AssessFeasibilityInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                problem=ProblemBrief.model_validate(state["problem"]),
                evidence_tiers=[EvidenceTier(t) for t in state["evidence_tiers"]],
                design=FYPDesign.model_validate(state["design"]),
                definition=ProjectDefinition.model_validate(state["definition"]),
                strategy=AIStrategy.model_validate(state["strategy"]),
                dataset=DatasetOption.model_validate(state["dataset"]),
                models=ModelPlan.model_validate(state["models"]),
                technology=TechnologyPlan.model_validate(state["technology"]),
                technical=TechnicalPlan.model_validate(state["technical"]),
            ),
            on_progress=_forwarder(),
        )
        return {
            "report_output": output.model_dump(mode="json"),
            "report": output.report.model_dump(mode="json"),
            "report_id": state.get("report_id") or str(uuid.uuid4()),
            "workflow_state": WorkflowState.FEASIBILITY.value,
        }

    return assess_feasibility_node


def feasibility_review_node(state: FeasibilityState) -> dict:
    """
    Pause until the student accepts the feasibility report (mandatory HITL).
    Resumed with Command(resume={"action": "accept", "report_id": …}).
    """
    decision = interrupt({
        "stage": WorkflowState.FEASIBILITY.value,
        "report_id": state.get("report_id"),
        "prompt": "Read the feasibility report and accept it to continue.",
    })
    action = decision.get("action") if isinstance(decision, dict) else None
    if action != ACCEPT:
        raise ValueError(f"Unknown feasibility review action: {action!r}.")
    if decision.get("report_id") != state.get("report_id"):
        raise ValueError("Only this project's feasibility report can be accepted.")
    return {"accepted_report_id": state["report_id"], "workflow_state": WorkflowState.FEASIBILITY_ACCEPTED.value}
