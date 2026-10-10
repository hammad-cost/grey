"""
The feasibility dimensions Grey can decide from facts in the Project Brain —
plain code, no AI (Release 0.12).

  evidence_strength       — the evidence tiers behind the chosen problem
  data_availability       — the selected dataset (public / generated / collected, fit)
  hardware_requirement    — the essential hardware in the approved technology plan
  cost                    — the costliest essential hardware item
  evaluation_possibility  — the metrics, tests and baseline in the technical plan
  demonstrability         — the interface in the architecture
"""
from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import (
    AssessedBy,
    ComponentKind,
    CostLevel,
    DatasetFit,
    DatasetKind,
    DimensionAssessment,
    EvidenceTier,
    FeasibilityDimension,
    FeasibilityLevel,
    HardwareKind,
)
from app.domains.fyp.skills.assess_feasibility.schemas import AssessFeasibilityInput

F, M, C = FeasibilityLevel.FAVOURABLE, FeasibilityLevel.MODERATE, FeasibilityLevel.CONCERN

# Hardware a student has to buy, borrow or learn to wire up.
SPECIAL_HARDWARE = {
    HardwareKind.DEDICATED_GPU, HardwareKind.CLOUD_GPU, HardwareKind.CAMERA, HardwareKind.SENSORS,
    HardwareKind.ARDUINO, HardwareKind.RASPBERRY_PI, HardwareKind.JETSON, HardwareKind.OTHER,
}
COST_ORDER = [CostLevel.NONE, CostLevel.LOW, CostLevel.MEDIUM, CostLevel.HIGH]


def _fact(dimension: FeasibilityDimension, level: FeasibilityLevel, finding: str, reason: str) -> DimensionAssessment:
    return DimensionAssessment(dimension=dimension, level=level, finding=finding, reason=reason,
                               assessed_by=AssessedBy.FACTS)


def evidence_strength(tiers: list[EvidenceTier]) -> DimensionAssessment:
    a, b = tiers.count(EvidenceTier.A), tiers.count(EvidenceTier.B)
    if a:
        return _fact(FeasibilityDimension.EVIDENCE_STRENGTH, F, "Strong",
                     f"{a} primary (Tier A) source{'s' if a > 1 else ''} back the problem.")
    if b:
        return _fact(FeasibilityDimension.EVIDENCE_STRENGTH, M, "Moderate",
                     f"{b} strong secondary (Tier B) source{'s' if b > 1 else ''}, but no primary source.")
    return _fact(FeasibilityDimension.EVIDENCE_STRENGTH, C, "Weak",
                 "Only discovery-level sources back the problem; a supervisor may ask for more evidence.")


def data_availability(input: AssessFeasibilityInput) -> DimensionAssessment:
    dataset = input.dataset
    if dataset.kind == DatasetKind.PUBLIC:
        if dataset.fit == DatasetFit.GOOD:
            return _fact(FeasibilityDimension.DATA_AVAILABILITY, F, "Available",
                         f"A public dataset ({dataset.name}) fits the problem as it is.")
        return _fact(FeasibilityDimension.DATA_AVAILABILITY, M, "Available with work",
                     f"A public dataset ({dataset.name}) fits after extra preparation.")
    made = "generate" if dataset.kind == DatasetKind.SYNTHETIC else "collect"
    return _fact(FeasibilityDimension.DATA_AVAILABILITY, M, f"Data you {made}",
                 f"No public dataset is used; you {made} the data yourself, which takes time to do well.")


def _essential_hardware(input: AssessFeasibilityInput):
    return [item for item in input.technology.hardware if item.essential]


def hardware_requirement(input: AssessFeasibilityInput) -> DimensionAssessment:
    essential = _essential_hardware(input)
    if any(item.cost == CostLevel.HIGH for item in essential):
        return _fact(FeasibilityDimension.HARDWARE_REQUIREMENT, C, "Expensive hardware",
                     "Essential hardware is expensive; check the cheaper alternative early.")
    special = [item.name for item in essential if item.kind in SPECIAL_HARDWARE]
    if special:
        return _fact(FeasibilityDimension.HARDWARE_REQUIREMENT, M, "Special hardware",
                     f"You need {', '.join(special)} as well as a normal laptop.")
    return _fact(FeasibilityDimension.HARDWARE_REQUIREMENT, F, "Low",
                 "A normal laptop and free online tools are enough.")


def cost(input: AssessFeasibilityInput) -> DimensionAssessment:
    costs = [item.cost for item in _essential_hardware(input)] or [CostLevel.NONE]
    highest = max(costs, key=COST_ORDER.index)
    if highest == CostLevel.HIGH:
        return _fact(FeasibilityDimension.COST, C, "High", "Some essential hardware or services cost a lot.")
    if highest == CostLevel.MEDIUM:
        return _fact(FeasibilityDimension.COST, M, "Medium", "Some essential hardware or services cost money.")
    return _fact(FeasibilityDimension.COST, F, "Low", "The essential tools are free or low cost.")


def evaluation_possibility(input: AssessFeasibilityInput) -> DimensionAssessment:
    evaluation = input.technical.evaluation
    needs_metrics = uses_ai(input.strategy.necessity)
    if (evaluation.metrics or not needs_metrics) and evaluation.tests and evaluation.baseline:
        return _fact(FeasibilityDimension.EVALUATION_POSSIBILITY, F, "Feasible",
                     f"{len(evaluation.metrics)} metric(s), {len(evaluation.tests)} system test(s) and a baseline are planned.")
    return _fact(FeasibilityDimension.EVALUATION_POSSIBILITY, M, "Partly planned",
                 "Tests are planned, but there is no baseline to compare against.")


def demonstrability(input: AssessFeasibilityInput) -> DimensionAssessment:
    interfaces = [c.name for c in input.technical.architecture.components if c.kind == ComponentKind.INTERFACE]
    if interfaces:
        return _fact(FeasibilityDimension.DEMONSTRABILITY, F, "Easy to demonstrate",
                     f"The {interfaces[0]} shows the results to the user.")
    return _fact(FeasibilityDimension.DEMONSTRABILITY, C, "Hard to demonstrate", "There is no screen to show the results on.")


def fact_dimensions(input: AssessFeasibilityInput) -> list[DimensionAssessment]:
    """The six dimensions decided from facts in the Project Brain."""
    return [
        evidence_strength(input.evidence_tiers),
        data_availability(input),
        hardware_requirement(input),
        cost(input),
        evaluation_possibility(input),
        demonstrability(input),
    ]
