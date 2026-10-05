"""
Builds the facts sent to the language model, from the stored evidence.

What is sent for each source: a short ref (E1, E2, …), title, organization,
type, tier, category, date, and its three short texts.

What is NOT sent: URLs (the model can't invent links — they are re-attached
from the database later), database ids, search queries, provider names, or
anything about the student.

Size: Groq's free tier allows about 8,000 tokens per minute, so the context
is kept small — the strongest sources first, long texts shortened, and
sources dropped from the weak end until it fits the budget.
"""
import json
from dataclasses import dataclass

from app.core.brain.schemas import EvidenceTier, StoredEvidenceSource

MAX_SOURCES = 20
MAX_TEXT_CHARS = 300
MAX_CONTEXT_TOKENS = 2_500       # rough budget for the evidence part of the request
MIN_SOURCES = 3


class NotEnoughEvidenceError(Exception):
    """There isn't enough usable evidence to look for problems (the LLM is not called)."""


@dataclass
class ProblemContext:
    """The model's input, and how to turn its refs back into stored evidence."""
    llm_input: dict
    sources_by_ref: dict[str, StoredEvidenceSource]


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1].rstrip() + "…"


def _source_entry(ref: str, source: StoredEvidenceSource) -> dict:
    return {
        "ref": ref,
        "title": _short(source.title),
        "organization": _short(source.organization),
        "source_type": source.source_type.value,
        "tier": source.evidence_tier.value,
        "category": source.research_category.value,
        "published": source.published_date.isoformat() if source.published_date else None,
        "problem_addressed": _short(source.problem_addressed),
        "relevant_insight": _short(source.relevant_insight),
        "why_it_matters": _short(source.why_it_matters),
    }


def _tokens(data: dict) -> int:
    return len(json.dumps(data, ensure_ascii=False)) // 4 + 1


def build_context(industry: str, branch: str, evidence: list[StoredEvidenceSource]) -> ProblemContext:
    """
    Choose and shorten the evidence for the model.

    Raises:
        NotEnoughEvidenceError: fewer than MIN_SOURCES sources, or no Tier A/B source
                                (the blueprint wants strong evidence behind every problem).
    """
    ordered = sorted(
        evidence,
        key=lambda s: (s.evidence_tier.value, -(s.published_date.toordinal() if s.published_date else 0), s.title),
    )[:MAX_SOURCES]

    if len(ordered) < MIN_SOURCES:
        raise NotEnoughEvidenceError(f"Only {len(ordered)} sources; at least {MIN_SOURCES} are needed.")
    if not any(s.evidence_tier in (EvidenceTier.A, EvidenceTier.B) for s in ordered):
        raise NotEnoughEvidenceError("No Tier A or B evidence to support a problem.")

    # Drop the weakest sources until the context fits the budget.
    while True:
        entries = [_source_entry(f"E{i}", s) for i, s in enumerate(ordered, start=1)]
        llm_input = {"industry": industry, "branch": branch, "evidence": entries}
        if _tokens(llm_input) <= MAX_CONTEXT_TOKENS or len(ordered) <= MIN_SOURCES:
            break
        ordered = ordered[:-1]

    return ProblemContext(
        llm_input=llm_input,
        sources_by_ref={f"E{i}": s for i, s in enumerate(ordered, start=1)},
    )
