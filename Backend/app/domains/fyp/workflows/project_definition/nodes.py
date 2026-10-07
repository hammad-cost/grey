"""
Project Definition workflow nodes (Release 0.6).

Rules (same as the other workflows):
  - Nodes never touch the database — the runner saves results to the Brain.
  - Skills are looked up by name in the Skill Registry, never created here.
  - Nodes forward only safe progress (step labels), never model reasoning.
  - The student's scope review is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import (
    FunctionalArea,
    FYPDesign,
    ScopeKind,
    StoredScopeItem,
    WorkflowState,
)
from app.core.brain.scope_rules import move_scope_item
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.define_project import DefineProjectInput, DefinitionProgress
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.workflows.project_definition.state import ProjectDefinitionState

# Name the skill is registered under in the Skill Registry.
DEFINE_SKILL_NAME = "define_project"

# Marks a progress update on LangGraph's custom stream.
DEFINITION_PROGRESS_KIND = "project_definition_progress"

MOVE = "move"
APPROVE = "approve"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: DefinitionProgress) -> None:
        write({"kind": DEFINITION_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_define_project_node(skills: SkillRegistry):
    """
    Build the define_project node: write the problem definition, scope and
    proposed solution (blueprint §19–21). The definition and each scope item
    get new ids; the runner saves them to the Brain with the same ids, so the
    review step can check moves and approval.
    """

    async def define_project_node(state: ProjectDefinitionState) -> dict:
        output = await skills.get(DEFINE_SKILL_NAME).execute(
            DefineProjectInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                area=FunctionalArea.model_validate(state["area"]),
                problem=ProblemBrief.model_validate(state["problem"]),
                design=FYPDesign.model_validate(state["design"]),
            ),
            on_progress=_forwarder(),
        )

        # The skill lists core, then optional, then out-of-scope features.
        positions: dict[ScopeKind, int] = {}
        scope = []
        for item in output.definition.scope:
            position = positions.get(item.kind, 0)
            positions[item.kind] = position + 1
            scope.append(StoredScopeItem(id=str(uuid.uuid4()), position=position, **item.model_dump()))

        return {
            "definition_output": output.model_dump(mode="json"),
            "definition_id": str(uuid.uuid4()),
            "scope": [item.model_dump(mode="json") for item in scope],
            "workflow_state": WorkflowState.SCOPE.value,
        }

    return define_project_node


def scope_review_node(state: ProjectDefinitionState) -> dict:
    """
    Pause until the student moves a feature or approves the scope (mandatory
    HITL). The API resumes the graph with
    Command(resume={"action": "move", "item_id": …, "to": "core" | "optional" | "out_of_scope"}) or
    Command(resume={"action": "approve", "definition_id": …}).
    A move comes back here for the next decision; approval ends the workflow.
    """
    decision = interrupt({
        "stage": WorkflowState.SCOPE.value,
        "definition_id": state.get("definition_id"),
        "prompt": "Move features between core, optional and out of scope, then approve the scope.",
    })

    action = decision.get("action") if isinstance(decision, dict) else None
    if action == MOVE:
        items = [StoredScopeItem.model_validate(item) for item in state.get("scope", [])]
        moved = move_scope_item(items, decision.get("item_id"), ScopeKind(decision.get("to")))   # ScopeChangeError
        return {"scope": [item.model_dump(mode="json") for item in moved]}
    if action == APPROVE:
        if decision.get("definition_id") != state.get("definition_id"):
            raise ValueError("Only this project's definition can be approved.")
        return {
            "approved_definition_id": state["definition_id"],
            "workflow_state": WorkflowState.SCOPE_APPROVED.value,
        }
    raise ValueError(f"Unknown scope review action: {action!r}.")


def after_review(state: ProjectDefinitionState) -> str:
    """Approved → the workflow ends. Otherwise (a move) → back to the review."""
    return "approved" if state.get("approved_definition_id") else "review"
