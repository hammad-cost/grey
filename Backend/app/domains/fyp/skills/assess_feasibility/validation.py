"""
Checks the model's feasibility judgement and builds the full report. Plain code — no AI.

  unknown_choice       — a dimension or level that isn't on Grey's lists
  wrong_dimensions     — not exactly the seven judgement dimensions, each once
  empty / too_long     — a text is empty, or far longer than asked for
  wrong_count          — 1-5 main risks
  contains_url         — a link appears anywhere
  states_overall       — the summary states a High / Medium / Low rating (Grey computes it)

The six fact dimensions come from facts.py; the overall rating and its reason
come from feasibility_rules.py.
"""
import re

from app.core.brain.feasibility_rules import overall_feasibility, overall_reason
from app.core.brain.schemas import (
    AssessedBy,
    DimensionAssessment,
    FeasibilityDimension,
    FeasibilityLevel,
    FeasibilityReport,
    FeasibilityRisk,
)
from app.domains.fyp.skills.assess_feasibility.facts import fact_dimensions
from app.domains.fyp.skills.assess_feasibility.schemas import (
    JUDGEMENT_DIMENSIONS,
    AssessFeasibilityInput,
    LLMFeasibilityDraft,
)
from app.domains.fyp.skills.fyp_design_shared import contains_url

MAX_FINDING_CHARS = 60
MAX_TEXT_CHARS = 400
RISK_COUNT = (1, 5)
_OVERALL = re.compile(r"\b(overall|feasibility)\b[^.]{0,30}\b(high|medium|low)\b", re.IGNORECASE)


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _clean(text: str) -> str:
    return " ".join(text.split())


def _text(value: str, limit: int) -> str:
    text = _clean(value)
    if not text:
        raise _Rejected("empty")
    if len(text) > limit:
        raise _Rejected("too_long")
    return text


def _choice(value: str, enum: type):
    try:
        return enum(value.strip().lower())
    except ValueError:
        raise _Rejected("unknown_choice") from None


def _build(draft: LLMFeasibilityDraft, input: AssessFeasibilityInput) -> FeasibilityReport:
    judgements = [
        DimensionAssessment(
            dimension=_choice(j.dimension, FeasibilityDimension),
            level=_choice(j.level, FeasibilityLevel),
            finding=_text(j.finding, MAX_FINDING_CHARS),
            reason=_text(j.reason, MAX_TEXT_CHARS),
            assessed_by=AssessedBy.JUDGEMENT,
        )
        for j in draft.judgements
    ]
    if sorted(j.dimension for j in judgements) != sorted(JUDGEMENT_DIMENSIONS):
        raise _Rejected("wrong_dimensions")
    if not RISK_COUNT[0] <= len(draft.main_risks) <= RISK_COUNT[1]:
        raise _Rejected("wrong_count")
    risks = [
        FeasibilityRisk(risk=_text(r.risk, MAX_TEXT_CHARS), mitigation=_text(r.mitigation, MAX_TEXT_CHARS))
        for r in draft.main_risks
    ]
    summary = _text(draft.summary, MAX_TEXT_CHARS)
    if _OVERALL.search(summary):
        raise _Rejected("states_overall")
    by_dimension = {d.dimension: d for d in [*fact_dimensions(input), *judgements]}
    dimensions = [by_dimension[d] for d in FeasibilityDimension]     # the blueprint's order
    return FeasibilityReport(
        summary=summary,
        dimensions=dimensions,
        main_risks=risks,
        overall=overall_feasibility(dimensions),
        overall_reason=overall_reason(dimensions),
    )


def check_feasibility_draft(
    draft: LLMFeasibilityDraft, input: AssessFeasibilityInput
) -> tuple[FeasibilityReport | None, str | None]:
    """Turn a draft into the full FeasibilityReport, or return (None, the reason it was rejected)."""
    try:
        report = _build(draft, input)
    except _Rejected as rejected:
        return None, rejected.reason
    texts = [report.summary] + [t for d in report.dimensions for t in (d.finding, d.reason)]
    texts += [t for r in report.main_risks for t in (r.risk, r.mitigation)]
    if any(contains_url(t) for t in texts):
        return None, "contains_url"
    return report, None
