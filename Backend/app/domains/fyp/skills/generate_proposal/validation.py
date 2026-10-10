"""
Checks the model's narrative sections. Plain code — no AI.

  unknown_choice    — a section id that isn't a proposal section
  wrong_sections    — not exactly the sections asked for, each once
  wrong_count       — paragraphs / objectives outside the allowed counts
  empty / too_long  — a text is empty, or far longer than asked for
  contains_url      — a link (http://, https://, www.) appears
  unknown_citation  — a [n] that isn't one of the evidence numbers
  invented_number   — a percentage the approved decisions never state
"""
import re

from app.core.brain.proposal_rules import cited_numbers
from app.core.brain.schemas import ProposalSection, ProposalSectionId, WrittenBy
from app.domains.fyp.skills.generate_proposal.schemas import MODEL_SECTION_SOURCES, SECTION_TITLES, LLMSectionsDraft

MAX_PARAGRAPH_CHARS = 1_400
MAX_ITEM_CHARS = 300
PARAGRAPHS = (1, 3)
OBJECTIVES = (3, 6)

_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _clean(text: str) -> str:
    return " ".join(text.split())


def _texts(values: list[str], limit: int) -> list[str]:
    texts = [_clean(v) for v in values]
    if any(not t for t in texts):
        raise _Rejected("empty")
    if any(len(t) > limit for t in texts):
        raise _Rejected("too_long")
    return texts


def check_sections_draft(
    draft: LLMSectionsDraft,
    wanted: list[ProposalSectionId],
    reference_count: int,
    context_text: str,
) -> tuple[dict[ProposalSectionId, ProposalSection] | None, str | None]:
    """Turn the draft into sections, or return (None, the reason it was rejected)."""
    sections: dict[ProposalSectionId, ProposalSection] = {}
    allowed_numbers = set(range(1, reference_count + 1))
    known_percents = {p.replace(" ", "") for p in _PERCENT.findall(context_text)}
    try:
        for s in draft.sections:
            try:
                section_id = ProposalSectionId(s.id.strip().lower())
            except ValueError:
                raise _Rejected("unknown_choice") from None
            if section_id not in wanted or section_id in sections:
                raise _Rejected("wrong_sections")
            paragraphs = _texts(s.paragraphs, MAX_PARAGRAPH_CHARS)
            items = _texts(s.items, MAX_ITEM_CHARS)
            if section_id == ProposalSectionId.OBJECTIVES:
                if not OBJECTIVES[0] <= len(items) <= OBJECTIVES[1] or len(paragraphs) > 1:
                    raise _Rejected("wrong_count")
            elif not PARAGRAPHS[0] <= len(paragraphs) <= PARAGRAPHS[1] or items:
                raise _Rejected("wrong_count")
            for text in [*paragraphs, *items]:
                if _LINK.search(text):
                    raise _Rejected("contains_url")
                if not cited_numbers(text) <= allowed_numbers:
                    raise _Rejected("unknown_citation")
                if any(p.replace(" ", "") not in known_percents for p in _PERCENT.findall(text)):
                    raise _Rejected("invented_number")
            sections[section_id] = ProposalSection(
                id=section_id, title=SECTION_TITLES[section_id], paragraphs=paragraphs, items=items,
                sources=MODEL_SECTION_SOURCES[section_id], written_by=WrittenBy.MODEL,
            )
        if set(sections) != set(wanted):
            raise _Rejected("wrong_sections")
    except _Rejected as rejected:
        return None, rejected.reason
    return sections, None
