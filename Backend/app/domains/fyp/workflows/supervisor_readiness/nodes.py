"""
Supervisor Readiness workflow nodes (Release 0.13). Nodes never touch the
database; the skill comes from the Skill Registry; confirmation is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.schemas import WorkflowState
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.prepare_supervisor_brief import BriefProgress, SupervisorBriefInput
from app.domains.fyp.workflows.supervisor_readiness.state import SupervisorReadinessState

BRIEF_SKILL_NAME = "prepare_supervisor_brief"
BRIEF_PROGRESS_KIND = "supervisor_brief_progress"
CONFIRM = "confirm"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: BriefProgress) -> None:
        write({"kind": BRIEF_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_prepare_brief_node(skills: SkillRegistry):
    """Build the prepare_brief node (blueprint §33–35)."""

    async def prepare_brief_node(state: SupervisorReadinessState) -> dict:
        output = await skills.get(BRIEF_SKILL_NAME).execute(
            SupervisorBriefInput.model_validate(state["inputs"]), on_progress=_forwarder()
        )
        return {
            "brief_output": output.model_dump(mode="json"),
            "brief": output.brief.model_dump(mode="json"),
            "brief_id": state.get("brief_id") or str(uuid.uuid4()),
            "workflow_state": WorkflowState.SUPERVISOR_READINESS.value,
        }

    return prepare_brief_node


def readiness_review_node(state: SupervisorReadinessState) -> dict:
    """
    Pause until the student confirms they've read the brief and are ready (mandatory HITL).
    Resumed with Command(resume={"action": "confirm", "brief_id": …}).
    """
    decision = interrupt({
        "stage": WorkflowState.SUPERVISOR_READINESS.value,
        "brief_id": state.get("brief_id"),
        "prompt": "Read the readiness checks, the summary and the likely questions, then confirm you're ready.",
    })
    action = decision.get("action") if isinstance(decision, dict) else None
    if action != CONFIRM:
        raise ValueError(f"Unknown supervisor readiness action: {action!r}.")
    if decision.get("brief_id") != state.get("brief_id"):
        raise ValueError("Only this project's supervisor brief can be confirmed.")
    return {"confirmed_brief_id": state["brief_id"], "workflow_state": WorkflowState.SUPERVISOR_READY.value}
