"""
Feasibility rules (Release 0.12) — plain code, no AI.

The overall rating is never the model's opinion: it is computed here from the
13 dimension levels, so the same report always gets the same rating.

  - favourable counts 2, moderate 1, concern 0
  - 3 or more concerns → Low
  - a concern on time or technical complexity caps the rating at Medium
  - otherwise: average ≥ 1.5 → High, ≥ 1.0 → Medium, else Low
"""
from app.core.brain.schemas import (
    DimensionAssessment,
    FeasibilityDimension,
    FeasibilityLevel,
    FeasibilityReport,
    OverallFeasibility,
)

POINTS = {FeasibilityLevel.FAVOURABLE: 2, FeasibilityLevel.MODERATE: 1, FeasibilityLevel.CONCERN: 0}
CAPPING_DIMENSIONS = {FeasibilityDimension.TIME, FeasibilityDimension.TECHNICAL_COMPLEXITY}
LOW_AT_CONCERNS = 3

# Display order (the blueprint's order) and plain names.
DIMENSION_NAMES = {
    FeasibilityDimension.PROBLEM_RELEVANCE: "Problem relevance",
    FeasibilityDimension.EVIDENCE_STRENGTH: "Evidence strength",
    FeasibilityDimension.DATA_AVAILABILITY: "Data availability",
    FeasibilityDimension.TECHNICAL_COMPLEXITY: "Technical complexity",
    FeasibilityDimension.HARDWARE_REQUIREMENT: "Hardware requirement",
    FeasibilityDimension.COST: "Cost",
    FeasibilityDimension.TIME: "Time",
    FeasibilityDimension.EVALUATION_POSSIBILITY: "Evaluation possibility",
    FeasibilityDimension.EXTERNAL_DEPENDENCIES: "External dependencies",
    FeasibilityDimension.ETHICAL_LEGAL: "Ethical / legal concerns",
    FeasibilityDimension.DEMONSTRABILITY: "Demonstrability",
    FeasibilityDimension.RISK: "Risk",
    FeasibilityDimension.NOVELTY: "Novelty",
}


class FeasibilityRuleError(ValueError):
    """The report breaks a rule."""


def overall_feasibility(dimensions: list[DimensionAssessment]) -> OverallFeasibility:
    """The overall rating for a set of dimension levels (see the module docstring)."""
    levels = {d.dimension: d.level for d in dimensions}
    concerns = [dim for dim, level in levels.items() if level == FeasibilityLevel.CONCERN]
    if len(concerns) >= LOW_AT_CONCERNS:
        return OverallFeasibility.LOW
    average = sum(POINTS[level] for level in levels.values()) / max(1, len(levels))
    rating = (
        OverallFeasibility.HIGH if average >= 1.5
        else OverallFeasibility.MEDIUM if average >= 1.0
        else OverallFeasibility.LOW
    )
    if rating == OverallFeasibility.HIGH and CAPPING_DIMENSIONS & set(concerns):
        return OverallFeasibility.MEDIUM
    return rating


def overall_reason(dimensions: list[DimensionAssessment]) -> str:
    """A plain explanation of how the overall rating was reached."""
    counts = {level: sum(1 for d in dimensions if d.level == level) for level in FeasibilityLevel}
    concerns = [DIMENSION_NAMES[d.dimension].lower() for d in dimensions if d.level == FeasibilityLevel.CONCERN]
    text = (
        f"{counts[FeasibilityLevel.FAVOURABLE]} of {len(dimensions)} dimensions are favourable, "
        f"{counts[FeasibilityLevel.MODERATE]} moderate and {counts[FeasibilityLevel.CONCERN]} a concern"
    )
    return text + (f" ({', '.join(concerns)})." if concerns else ".")


def report_rule_broken(report: FeasibilityReport) -> str | None:
    """The first rule the report breaks (a short code), or None."""
    dimensions = [d.dimension for d in report.dimensions]
    if sorted(dimensions) != sorted(FeasibilityDimension):
        return "missing_dimension"
    if report.overall != overall_feasibility(report.dimensions):
        return "overall_mismatch"
    return None


def check_report(report: FeasibilityReport) -> None:
    """Raise FeasibilityRuleError if the report breaks a rule."""
    broken = report_rule_broken(report)
    if broken is not None:
        raise FeasibilityRuleError(f"The feasibility report breaks a rule ({broken}).")
