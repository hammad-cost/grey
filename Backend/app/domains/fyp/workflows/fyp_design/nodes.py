"""
FYP Design workflow nodes (Release 0.5).

Rules (same as the discovery workflow):
  - Nodes never touch the database — the runner saves results to the Brain.
  - Skills are looked up by name in the Skill Registry, never created here.
  - Nodes forward only safe progress (step labels), never model reasoning.
  - The student's review is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import MAX_FYP_ADJUSTMENTS, FunctionalArea, FYPAdjustment, FYPDesign, WorkflowState
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.classify_area import ClassifyAreaInput
from app.domains.fyp.skills.design_fyp import DesignFYPInput
from app.domains.fyp.skills.fyp_design_shared import DesignProgress, ProblemBrief
from app.domains.fyp.workflows.fyp_design.state import FYPDesignState

# Names the skills are registered under in the Skill Registry.
AREA_SKILL_NAME = "classify_area"
DESIGN_SKILL_NAME = "design_fyp"

# Marks a progress update on LangGraph's custom stream.
DESIGN_PROGRESS_KIND = "fyp_design_progress"

APPROVE = "approve"
ADJUST = "adjust"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: DesignProgress) -> None:
        write({"kind": DESIGN_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_area_classification_node(skills: SkillRegistry):
    """Build the area_classification node: where does the chosen problem sit? (blueprint §16)"""

    async def area_classification_node(state: FYPDesignState) -> dict:
        output = await skills.get(AREA_SKILL_NAME).execute(
            ClassifyAreaInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                problem=ProblemBrief.model_validate(state["problem"]),
            ),
            on_progress=_forwarder(),
        )
        return {
            "area": output.area.model_dump(mode="json"),
            "area_output": output.model_dump(mode="json"),
            "workflow_state": WorkflowState.AREA_CLASSIFICATION.value,
        }

    return area_classification_node


def make_fyp_design_node(skills: SkillRegistry):
    """
    Build the fyp_design node: design the FYP, or redesign it when the review
    step recorded an adjustment. Each design gets a new id; the runner saves it
    to the Brain with the same id, so the review step can check approvals.
    """

    async def fyp_design_node(state: FYPDesignState) -> dict:
        request = state.get("adjustment")
        previous = state.get("design") if request else None
        output = await skills.get(DESIGN_SKILL_NAME).execute(
            DesignFYPInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                area=FunctionalArea.model_validate(state["area"]),
                problem=ProblemBrief.model_validate(state["problem"]),
                adjustment=FYPAdjustment(request["adjustment"]) if request else None,
                note=request.get("note") if request else None,
                previous_design=FYPDesign.model_validate(previous) if previous else None,
            ),
            on_progress=_forwarder(),
        )
        return {
            "design": output.design.model_dump(mode="json"),
            "design_output": output.model_dump(mode="json"),
            "design_id": str(uuid.uuid4()),
            "adjustment": None,
            "workflow_state": WorkflowState.FYP_DESIGN.value,
        }

    return fyp_design_node


def fyp_review_node(state: FYPDesignState) -> dict:
    """
    Pause until the student approves the design or asks for one controlled
    redesign (mandatory HITL). The API resumes the graph with
    Command(resume={"action": "approve", "design_id": …}) or
    Command(resume={"action": "adjust", "adjustment": …, "note": …}).
    """
    used = state.get("adjustments_used", 0)
    decision = interrupt({
        "stage": WorkflowState.FYP_DESIGN.value,
        "design_id": state.get("design_id"),
        "adjustments_left": max(0, MAX_FYP_ADJUSTMENTS - used),
        "prompt": "Approve this FYP, or ask Grey to adjust it.",
    })

    action = decision.get("action") if isinstance(decision, dict) else None
    if action == APPROVE:
        if decision.get("design_id") != state.get("design_id"):
            raise ValueError("Only the current FYP design can be approved.")
        return {
            "approved_design_id": state["design_id"],
            "workflow_state": WorkflowState.APPROVED_FYP.value,
        }
    if action == ADJUST:
        if used >= MAX_FYP_ADJUSTMENTS:
            raise ValueError(f"All {MAX_FYP_ADJUSTMENTS} redesigns have been used.")
        adjustment = FYPAdjustment(decision.get("adjustment"))       # ValueError if not a controlled option
        return {
            "adjustment": {"adjustment": adjustment.value, "note": decision.get("note")},
            "adjustments_used": used + 1,
        }
    raise ValueError(f"Unknown FYP review action: {action!r}.")


def after_review(state: FYPDesignState) -> str:
    """Approved → the workflow ends. Otherwise → redesign."""
    return "approved" if state.get("approved_design_id") else "redesign"
