"""
Proposal rules (Release 0.14) — plain code, no AI.

  - every blueprint section appears once, in the blueprint's order (§36)
  - every section says where it came from (traceability, §37)
  - the text cites only references that exist ([1] … [n])
  - only sections the model wrote can be rewritten
"""
import re

from app.core.brain.schemas import Proposal, ProposalSectionId, WrittenBy

# Sections the model writes (the narrative); every other section is built in code.
MODEL_SECTIONS = [
    ProposalSectionId.INTRODUCTION,
    ProposalSectionId.BACKGROUND,
    ProposalSectionId.PROBLEM_STATEMENT,
    ProposalSectionId.MOTIVATION,
    ProposalSectionId.REAL_WORLD_EVIDENCE,
    ProposalSectionId.PROPOSED_SOLUTION,
    ProposalSectionId.AIM,
    ProposalSectionId.OBJECTIVES,
    ProposalSectionId.METHODOLOGY,
    ProposalSectionId.EXPECTED_OUTCOMES,
    ProposalSectionId.LIMITATIONS,
]

_CITATION = re.compile(r"\[(\d+)\]")


class ProposalRuleError(ValueError):
    """The proposal breaks a rule."""


def cited_numbers(text: str) -> set[int]:
    return {int(n) for n in _CITATION.findall(text)}


def proposal_rule_broken(proposal: Proposal) -> str | None:
    """The first rule the proposal breaks (a short code), or None."""
    if [s.id for s in proposal.sections] != list(ProposalSectionId):
        return "wrong_sections"
    for section in proposal.sections:
        expected = WrittenBy.MODEL if section.id in MODEL_SECTIONS else WrittenBy.GREY
        if section.written_by != expected:
            return "wrong_author"
    known = {r.number for r in proposal.references}
    for section in proposal.sections:
        if section.id == ProposalSectionId.REFERENCES:
            continue
        for text in [*section.paragraphs, *section.items]:
            if not cited_numbers(text) <= known:
                return "unknown_citation"
    return None


def check_proposal(proposal: Proposal) -> None:
    """Raise ProposalRuleError if the proposal breaks a rule."""
    broken = proposal_rule_broken(proposal)
    if broken is not None:
        raise ProposalRuleError(f"The proposal breaks a rule ({broken}).")


def rewrite_problem(section: ProposalSectionId) -> str | None:
    """Why this section can't be rewritten (a message), or None if it can."""
    if section not in MODEL_SECTIONS:
        return "This section is built from your approved decisions, so it can't be rewritten."
    return None
