"""
Proposal workflow nodes (Release 0.14). Nodes never touch the database; the
skill comes from the Skill Registry; finalizing is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.proposal_rules import rewrite_problem
from app.core.brain.schemas import MAX_PROPOSAL_REWRITES, Proposal, ProposalSectionId, WorkflowState
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.generate_proposal import GenerateProposalInput, ProposalProgress
from app.domains.fyp.skills.prepare_supervisor_brief import SupervisorBriefInput
from app.domains.fyp.workflows.proposal.state import ProposalState

PROPOSAL_SKILL_NAME = "generate_proposal"
PROPOSAL_PROGRESS_KIND = "proposal_progress"

FINALIZE = "finalize"
REWRITE = "rewrite"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: ProposalProgress) -> None:
        write({"kind": PROPOSAL_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_generate_proposal_node(skills: SkillRegistry):
    """Build the generate_proposal node (blueprint §36–37): the whole proposal, or one rewritten section."""

    async def generate_proposal_node(state: ProposalState) -> dict:
        section = state.get("rewrite_section")
        previous = state.get("proposal")
        output = await skills.get(PROPOSAL_SKILL_NAME).execute(
            GenerateProposalInput(
                decisions=SupervisorBriefInput.model_validate(state["inputs"]),
                rewrite_section=ProposalSectionId(section) if section else None,
                previous=Proposal.model_validate(previous) if section and previous else None,
            ),
            on_progress=_forwarder(),
        )
        return {
            "proposal_output": output.model_dump(mode="json"),
            "proposal": output.proposal.model_dump(mode="json"),
            "proposal_id": state.get("proposal_id") or str(uuid.uuid4()),
            "rewrites_used": state.get("rewrites_used", 0) + (1 if section else 0),
            "rewrite_section": None,
            "workflow_state": WorkflowState.PROPOSAL_GENERATION.value,
        }

    return generate_proposal_node


def proposal_review_node(state: ProposalState) -> dict:
    """
    Pause until the student finalizes the proposal or asks for one section to be
    rewritten (mandatory HITL). Resumed with
    Command(resume={"action": "finalize", "proposal_id": …}) or
    Command(resume={"action": "rewrite", "section": "<section id>"}).
    """
    used = state.get("rewrites_used", 0)
    decision = interrupt({
        "stage": WorkflowState.PROPOSAL_GENERATION.value,
        "proposal_id": state.get("proposal_id"),
        "rewrites_left": max(0, MAX_PROPOSAL_REWRITES - used),
        "prompt": "Read your proposal. Rewrite a section, or finalize it.",
    })
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == FINALIZE:
        if decision.get("proposal_id") != state.get("proposal_id"):
            raise ValueError("Only this project's proposal can be finalized.")
        return {"finalized_id": state["proposal_id"], "workflow_state": WorkflowState.COMPLETE.value}
    if action == REWRITE:
        if used >= MAX_PROPOSAL_REWRITES:
            raise ValueError(f"All {MAX_PROPOSAL_REWRITES} rewrites have been used.")
        section = ProposalSectionId(decision.get("section"))
        problem = rewrite_problem(section)
        if problem is not None:
            raise ValueError(problem)
        return {"rewrite_section": section.value}
    raise ValueError(f"Unknown proposal review action: {action!r}.")


def after_review(state: ProposalState) -> str:
    return "finalized" if state.get("finalized_id") else "rewrite"
