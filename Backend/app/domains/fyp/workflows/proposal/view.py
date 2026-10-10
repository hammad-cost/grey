"""What the student sees about the proposal (Release 0.14), built from the Project Brain."""
from pydantic import BaseModel

from app.core.brain.proposal_rules import MODEL_SECTIONS
from app.core.brain.schemas import (
    MAX_PROPOSAL_REWRITES,
    ProposalSectionId,
    ProposalStatus,
    StoredProposal,
    SupervisorBriefStatus,
    WorkspaceBrainSnapshot,
)


class ProposalView(BaseModel):
    """Everything the proposal workspace needs, in one piece."""
    fyp_title: str
    proposal: StoredProposal | None = None
    rewrites_left: int = MAX_PROPOSAL_REWRITES
    max_rewrites: int = MAX_PROPOSAL_REWRITES
    rewritable_sections: list[ProposalSectionId] = []      # what the student may ask Grey to rewrite now


def build_proposal_view(snapshot: WorkspaceBrainSnapshot) -> ProposalView | None:
    """The proposal view, or None until the student is ready for their supervisor."""
    design, brief = snapshot.fyp_design, snapshot.supervisor_brief
    if design is None or brief is None or brief.status != SupervisorBriefStatus.CONFIRMED:
        return None
    proposal = snapshot.proposal
    left = max(0, MAX_PROPOSAL_REWRITES - proposal.rewrites_used) if proposal else MAX_PROPOSAL_REWRITES
    can_rewrite = proposal is not None and proposal.status == ProposalStatus.DRAFT and left > 0
    return ProposalView(
        fyp_title=design.title,
        proposal=proposal,
        rewrites_left=left,
        rewritable_sections=list(MODEL_SECTIONS) if can_rewrite else [],
    )
