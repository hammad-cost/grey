"""
Checks every problem draft the language model returns. Plain code — no AI.

The model is never trusted to grade itself. A draft becomes a ProblemCandidate
only if it passes every check below; otherwise it is dropped and the reason is
counted (the counts are saved on the problem run).

Per citation:
  unknown_ref        — the ref (e.g. "E9") isn't one of the sources we sent → dropped
  ungrounded         — the supporting point doesn't match the source's own text → dropped
Per draft:
  no_valid_evidence  — no citation survived
  only_tier_c        — no surviving citation is Tier A or B (blueprint §11)
  names_organization — an organization's name is in the title or FYP direction
                       (the problem must not be "copy this company's product")
  contains_url       — a URL appears anywhere (links only come from the database)
  too_long           — a field is far longer than asked for
Across drafts:
  duplicate          — same problem as a stronger draft (titles overlap, or both cite
                       several sources that are almost all the same) → merged into it
"""
import re
from collections import Counter

from app.core.brain.schemas import (
    MAX_PROBLEM_OPTIONS,
    EvidenceStrength,
    EvidenceTier,
    ProblemCandidate,
    ProblemEvidenceLink,
    StoredEvidenceSource,
)
from app.domains.fyp.skills.problem_extraction.schemas import LLMProblemDraft

MAX_TITLE_CHARS = 120
MAX_TEXT_CHARS = 600
MAX_CITATIONS = 4
GROUNDING_THRESHOLD = 0.5      # share of the supporting point's key words found in the source
TITLE_DUPLICATE_THRESHOLD = 0.6
SOURCE_DUPLICATE_THRESHOLD = 0.8

_URL = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|org|net|gov|edu|io|ai|example)\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "that", "this", "with", "from", "they", "their", "there", "which", "about", "into", "than",
    "have", "been", "were", "will", "would", "could", "should", "also", "more", "most", "such",
    "some", "when", "where", "while", "what", "these", "those", "using", "used", "make", "made",
}
_TEXT_FIELDS = ("title", "real_world_problem", "observed_solutions", "technical_problem",
                "why_it_matters", "possible_fyp_direction")


# ── Small text helpers ────────────────────────────────────────────────────────

def key_words(text: str) -> set[str]:
    """Meaningful words, lower-case, with a plural 's' removed (so 'alerts' matches 'alert')."""
    return {
        word[:-1] if word.endswith("s") and len(word) > 4 else word
        for word in _WORD.findall(text.lower())
        if len(word) >= 4 and word not in _STOPWORDS
    }


def is_grounded(supporting_point: str, source: StoredEvidenceSource) -> bool:
    """True if most key words of the supporting point appear in the source's own text."""
    point = key_words(supporting_point)
    if len(point) < 2:
        return False
    source_words = key_words(" ".join([
        source.title, source.problem_addressed, source.relevant_insight, source.why_it_matters,
    ]))
    return len(point & source_words) / len(point) >= GROUNDING_THRESHOLD


def organization_names(sources: list[StoredEvidenceSource]) -> set[str]:
    """Plain organization names, e.g. 'Northwind Analytics (sample startup)' → 'northwind analytics'."""
    names = set()
    for source in sources:
        name = source.organization.split("(")[0].strip().lower()
        if len(name) >= 4:
            names.add(name)
    return names


def _overlap(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ── One draft ─────────────────────────────────────────────────────────────────

def check_draft(
    draft: LLMProblemDraft,
    sources_by_ref: dict[str, StoredEvidenceSource],
    organizations: set[str],
    rejections: Counter,
) -> ProblemCandidate | None:
    """Turn one draft into a ProblemCandidate, or return None (and count why)."""
    texts = {field: getattr(draft, field).strip() for field in _TEXT_FIELDS}

    if any(_URL.search(text) for text in texts.values()) or any(
        _URL.search(c.supporting_point) for c in draft.evidence
    ):
        rejections["contains_url"] += 1
        return None
    if len(texts["title"]) > MAX_TITLE_CHARS or any(len(t) > MAX_TEXT_CHARS for t in texts.values()):
        rejections["too_long"] += 1
        return None
    named = (texts["title"] + " " + texts["possible_fyp_direction"]).lower()
    if any(re.search(rf"\b{re.escape(org)}\b", named) for org in organizations):
        rejections["names_organization"] += 1
        return None

    links: list[ProblemEvidenceLink] = []
    tiers: list[EvidenceTier] = []
    seen: set[str] = set()
    for citation in draft.evidence:
        ref = citation.ref.strip().upper()
        source = sources_by_ref.get(ref)
        if source is None:
            rejections["unknown_ref"] += 1
            continue
        if source.id in seen or len(links) >= MAX_CITATIONS:
            continue
        if not is_grounded(citation.supporting_point, source):
            rejections["ungrounded"] += 1
            continue
        seen.add(source.id)
        links.append(ProblemEvidenceLink(evidence_source_id=source.id,
                                         supporting_point=citation.supporting_point.strip()))
        tiers.append(source.evidence_tier)

    if not links:
        rejections["no_valid_evidence"] += 1
        return None
    if not any(tier in (EvidenceTier.A, EvidenceTier.B) for tier in tiers):
        rejections["only_tier_c"] += 1
        return None

    return ProblemCandidate(
        **texts,
        task_type=draft.task_type,
        evidence=links,
        evidence_strength=_strength(tiers),
    )


def _strength(tiers: list[EvidenceTier]) -> EvidenceStrength:
    counts = Counter(tiers)
    return EvidenceStrength(tier_a=counts[EvidenceTier.A], tier_b=counts[EvidenceTier.B],
                            tier_c=counts[EvidenceTier.C])


# ── Across drafts ─────────────────────────────────────────────────────────────

def _strength_key(candidate: ProblemCandidate, organizations_by_source: dict[str, str]) -> tuple:
    """Stronger first: more Tier A, then more distinct organizations, then fewer Tier C."""
    distinct_orgs = len({organizations_by_source[l.evidence_source_id] for l in candidate.evidence})
    s = candidate.evidence_strength
    return (-s.tier_a, -distinct_orgs, -s.tier_b, s.tier_c)


def _is_duplicate(a: ProblemCandidate, b: ProblemCandidate) -> bool:
    if _overlap(key_words(a.title), key_words(b.title)) >= TITLE_DUPLICATE_THRESHOLD:
        return True
    # Different problems often share one strong source, so sources only decide
    # when both problems cite several sources and almost all of them are the same.
    sources_a = {l.evidence_source_id for l in a.evidence}
    sources_b = {l.evidence_source_id for l in b.evidence}
    if min(len(sources_a), len(sources_b)) < 2:
        return False
    return _overlap(sources_a, sources_b) >= SOURCE_DUPLICATE_THRESHOLD


def _merge(keep: ProblemCandidate, extra: ProblemCandidate, tier_by_source: dict[str, EvidenceTier]) -> ProblemCandidate:
    """Add the duplicate's other sources to the kept problem (up to MAX_CITATIONS)."""
    links = list(keep.evidence)
    known = {l.evidence_source_id for l in links}
    for link in extra.evidence:
        if link.evidence_source_id not in known and len(links) < MAX_CITATIONS:
            links.append(link)
            known.add(link.evidence_source_id)
    return keep.model_copy(update={
        "evidence": links,
        "evidence_strength": _strength([tier_by_source[l.evidence_source_id] for l in links]),
    })


def select_candidates(
    drafts: list[LLMProblemDraft],
    sources_by_ref: dict[str, StoredEvidenceSource],
    rejections: Counter,
) -> list[ProblemCandidate]:
    """
    Check every draft, merge duplicates, rank strongest first, keep at most MAX_PROBLEM_OPTIONS.
    `rejections` is updated with the reason for everything dropped.
    """
    sources = list(sources_by_ref.values())
    organizations = organization_names(sources)
    organizations_by_source = {s.id: s.organization for s in sources}
    tier_by_source = {s.id: s.evidence_tier for s in sources}

    checked = [c for d in drafts if (c := check_draft(d, sources_by_ref, organizations, rejections))]
    checked.sort(key=lambda c: _strength_key(c, organizations_by_source))

    kept: list[ProblemCandidate] = []
    for candidate in checked:
        for index, existing in enumerate(kept):
            if _is_duplicate(existing, candidate):
                kept[index] = _merge(existing, candidate, tier_by_source)
                rejections["duplicate"] += 1
                break
        else:
            kept.append(candidate)

    kept.sort(key=lambda c: _strength_key(c, organizations_by_source))
    return kept[:MAX_PROBLEM_OPTIONS]
