"""
The proposal as Markdown (Release 0.14) — plain code, so the student can download
it and paste it into Word or Google Docs. Each section notes where it came from.
"""
from app.core.brain.schemas import Proposal, ProposalSectionId


def proposal_markdown(proposal: Proposal) -> str:
    lines = [f"# {proposal.title}", ""]
    for section in proposal.sections:
        if section.id == ProposalSectionId.PROJECT_TITLE:
            continue                                   # already the document heading
        lines += [f"## {section.title}", ""]
        for paragraph in section.paragraphs:
            lines += [paragraph, ""]
        if section.items:
            numbered = section.id in (ProposalSectionId.OBJECTIVES,)
            lines += [f"{n}. {item}" if numbered else f"- {item}" for n, item in enumerate(section.items, start=1)]
            lines.append("")
        lines += [f"*Source: {', '.join(section.sources)}*", ""]
    return "\n".join(lines).rstrip() + "\n"
