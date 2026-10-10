"""
LangGraph state for the Proposal workflow (Release 0.14).
Execution state only — the runner rebuilds it from the Project Brain when needed.
"""
from typing import TypedDict


class ProposalState(TypedDict, total=False):
    """
    inputs                  — every approved decision (a SupervisorBriefInput), as plain JSON data.
    proposal / proposal_id  — the Proposal and its id (the Brain uses the same id).
    proposal_output         — the generate_proposal skill's full result, until the runner saves it.
    rewrites_used           — how many section rewrites have been saved.
    rewrite_section         — the ProposalSectionId value being rewritten, else None.
    finalized_id            — set when the student finalizes; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    inputs: dict
    proposal: dict | None
    proposal_id: str | None
    proposal_output: dict | None
    rewrites_used: int
    rewrite_section: str | None
    finalized_id: str | None
