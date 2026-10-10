"""
Model Selection workflow nodes (Release 0.9).

Rules (same as the other workflows): nodes never touch the database, skills
come from the Skill Registry, only safe progress is forwarded, and the
student's approval is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.model_rules import research_problem
from app.core.brain.schemas import (
    MAX_MODEL_RESEARCHES,
    AIStrategy,
    DatasetOption,
    FunctionalArea,
    ModelCandidate,
    ModelPlan,
    ModelPreference,
    ProjectDefinition,
    WorkflowState,
)
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.find_models import FindModelsInput, ModelProgress
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.workflows.model_selection.state import ModelSelectionState

FIND_MODELS_SKILL_NAME = "find_models"
MODEL_PROGRESS_KIND = "model_progress"

APPROVE = "approve"
RESEARCH = "research"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: ModelProgress) -> None:
        write({"kind": MODEL_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_find_models_node(skills: SkillRegistry):
    """Build the find_models node: look for models, APIs and code (blueprint §26)."""

    async def find_models_node(state: ModelSelectionState) -> dict:
        preference = state.get("preference")
        previous = state.get("plan")
        output = await skills.get(FIND_MODELS_SKILL_NAME).execute(
            FindModelsInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                area=FunctionalArea.model_validate(state["area"]),
                problem=ProblemBrief.model_validate(state["problem"]),
                definition=ProjectDefinition.model_validate(state["definition"]),
                strategy=AIStrategy.model_validate(state["strategy"]),
                dataset=DatasetOption.model_validate(state["dataset"]),
                preference=ModelPreference(preference) if preference else None,
                previous_plan=ModelPlan.model_validate(previous) if preference and previous else None,
                known_candidates=[
                    ModelCandidate.model_validate(c) for c in state.get("known_candidates", [])
                ] if preference else [],
            ),
            on_progress=_forwarder(),
        )
        return {
            "plan_output": output.model_dump(mode="json"),
            "plan": output.plan.model_dump(mode="json"),
            "plan_id": state.get("plan_id") or str(uuid.uuid4()),
            "known_candidates": [c.model_dump(mode="json") for c in output.candidates],
            "researches_used": state.get("researches_used", 0) + (1 if preference else 0),
            "preference": None,
            "workflow_state": WorkflowState.MODEL_SELECTION.value,
        }

    return find_models_node


def model_review_node(state: ModelSelectionState) -> dict:
    """
    Pause until the student approves the model plan or asks Grey to look for
    other models (mandatory HITL). Resumed with
    Command(resume={"action": "approve", "plan_id": …}) or
    Command(resume={"action": "research", "preference": "other_options"}).
    """
    used = state.get("researches_used", 0)
    decision = interrupt({
        "stage": WorkflowState.MODEL_SELECTION.value,
        "plan_id": state.get("plan_id"),
        "researches_left": max(0, MAX_MODEL_RESEARCHES - used),
        "prompt": "Approve the model plan, or ask Grey to look for other models.",
    })

    action = decision.get("action") if isinstance(decision, dict) else None
    if action == APPROVE:
        if decision.get("plan_id") != state.get("plan_id"):
            raise ValueError("Only this project's model plan can be approved.")
        return {"approved_plan_id": state["plan_id"], "workflow_state": WorkflowState.MODELS_APPROVED.value}
    if action == RESEARCH:
        if used >= MAX_MODEL_RESEARCHES:
            raise ValueError(f"All {MAX_MODEL_RESEARCHES} new searches have been used.")
        preference = ModelPreference(decision.get("preference"))
        problem = research_problem(ModelPlan.model_validate(state["plan"]), preference)
        if problem is not None:
            raise ValueError(problem)
        return {"preference": preference.value}
    raise ValueError(f"Unknown model review action: {action!r}.")


def after_review(state: ModelSelectionState) -> str:
    """Approved → the workflow ends. Otherwise (a re-search) → back to find_models."""
    return "approved" if state.get("approved_plan_id") else "research"
