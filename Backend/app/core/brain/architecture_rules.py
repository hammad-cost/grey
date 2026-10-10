"""
Architecture and evaluation rules (Release 0.11) — plain code, no AI.

One place decides whether a technical plan is consistent, so the skill, the
workflow and the Project Brain apply the same rules:

  - component ids are unique, and every flow joins two known components
  - every component is connected to at least one flow
  - there is a user and an interface (the student must be able to demonstrate it)
  - a project that uses AI has a model component and AI metrics; one that
    doesn't has neither
  - the metrics match the AI task (error metrics for regression / forecasting,
    detection metrics for classification-type tasks)
  - metrics and system tests are not repeated; a baseline comparison names its baseline
"""
from app.core.brain.schemas import AITaskType, ComponentKind, Metric, SystemTestKind, TechnicalPlan

ERROR_METRICS = {Metric.MAE, Metric.RMSE}
DETECTION_METRICS = {
    Metric.ACCURACY, Metric.PRECISION, Metric.RECALL, Metric.F1_SCORE, Metric.AUC,
    Metric.FALSE_ALARM_RATE, Metric.DETECTION_RATE,
}
ERROR_TASKS = {AITaskType.REGRESSION, AITaskType.FORECASTING, AITaskType.TIME_SERIES_ANALYSIS}
DETECTION_TASKS = {
    AITaskType.CLASSIFICATION, AITaskType.ANOMALY_DETECTION, AITaskType.OBJECT_DETECTION,
    AITaskType.COMPUTER_VISION, AITaskType.NLP,
}


class ArchitectureRuleError(ValueError):
    """The plan breaks a rule."""


def allowed_metrics(task: AITaskType | None) -> set[Metric]:
    """The metrics that fit an AI task (all of them for tasks without a clear family)."""
    if task in ERROR_TASKS:
        return ERROR_METRICS
    if task in DETECTION_TASKS:
        return DETECTION_METRICS
    return set(Metric)


def plan_rule_broken(plan: TechnicalPlan, *, uses_ai: bool, task: AITaskType | None) -> str | None:
    """The first rule the plan breaks (a short code), or None if it is consistent."""
    components = plan.architecture.components
    ids = [c.id for c in components]
    if len(set(ids)) != len(ids):
        return "duplicate_component"
    flows = plan.architecture.flows
    if any(f.source not in ids or f.target not in ids or f.source == f.target for f in flows):
        return "unknown_component"
    connected = {f.source for f in flows} | {f.target for f in flows}
    if set(ids) - connected:
        return "unconnected_component"
    kinds = {c.kind for c in components}
    if ComponentKind.USER not in kinds or ComponentKind.INTERFACE not in kinds:
        return "missing_interface"

    metrics = [m.metric for m in plan.evaluation.metrics]
    if uses_ai:
        if ComponentKind.MODEL not in kinds:
            return "missing_model"
        if not metrics:
            return "missing_ai_metrics"
        if not set(metrics) <= allowed_metrics(task):
            return "metric_mismatch"
    elif ComponentKind.MODEL in kinds or metrics:
        return "ai_without_ai"
    if len(set(metrics)) != len(metrics):
        return "duplicate_metric"

    tests = [t.kind for t in plan.evaluation.tests]
    if len(set(tests)) != len(tests):
        return "duplicate_test"
    if SystemTestKind.BASELINE_COMPARISON in tests and not plan.evaluation.baseline:
        return "missing_baseline"
    return None


def check_plan(plan: TechnicalPlan, *, uses_ai: bool, task: AITaskType | None) -> None:
    """Raise ArchitectureRuleError if the plan breaks a rule."""
    broken = plan_rule_broken(plan, uses_ai=uses_ai, task=task)
    if broken is not None:
        raise ArchitectureRuleError(f"The technical plan breaks a rule ({broken}).")
