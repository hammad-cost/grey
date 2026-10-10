"""
Checks every technical plan the model returns. Plain code — no AI.

  unknown_choice      — a component kind, metric or test kind that isn't on Grey's lists
  empty               — a required text is empty
  wrong_count         — 4-10 components, 3-14 flows, 0-5 metrics, 1-5 tests
  too_long            — a text is far longer than asked for
  contains_url        — a link appears anywhere
  unknown_technology  — a component names a technology that isn't in the approved stack,
                        the selected dataset or the model plan
  … and the rules in architecture_rules.py (unknown_component, unconnected_component,
  missing_interface, missing_model, missing_ai_metrics, metric_mismatch, ai_without_ai, …)
"""
from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.architecture_rules import plan_rule_broken
from app.core.brain.schemas import (
    Architecture,
    ArchitectureComponent,
    ArchitectureFlow,
    ComponentKind,
    EvaluationMetric,
    EvaluationPlan,
    Metric,
    SystemTest,
    SystemTestKind,
    TechnicalPlan,
)
from app.domains.fyp.skills.design_architecture.schemas import DesignArchitectureInput, LLMTechnicalPlanDraft
from app.domains.fyp.skills.fyp_design_shared import contains_url

MAX_TEXT_CHARS = 400
MAX_NAME_CHARS = 80
COUNTS = {"components": (4, 10), "flows": (3, 14), "metrics": (0, 5), "tests": (1, 5)}


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _clean(text: str) -> str:
    return " ".join(text.split())


def _choice(value: str, enum: type):
    try:
        return enum(value.strip().lower())
    except ValueError:
        raise _Rejected("unknown_choice") from None


def _text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    text = _clean(value)
    if not text:
        raise _Rejected("empty")
    if len(text) > limit:
        raise _Rejected("too_long")
    return text


def known_technologies(input: DesignArchitectureInput) -> list[str]:
    """Names a component may use: the approved stack, the selected dataset and the model plan."""
    return [c.choice for c in input.technology.stack] + [input.dataset.name] + [o.name for o in input.models.options]


def _known(technology: str, known: list[str]) -> bool:
    t = technology.lower()
    return any(t in k.lower() or k.lower() in t for k in known)


def _build(draft: LLMTechnicalPlanDraft, known: list[str]) -> TechnicalPlan:
    for field, (low, high) in COUNTS.items():
        if not low <= len(getattr(draft, field)) <= high:
            raise _Rejected("wrong_count")
    components = []
    for c in draft.components:
        technology = _clean(c.technology) or None
        if technology is not None and not _known(technology, known):
            raise _Rejected("unknown_technology")
        components.append(ArchitectureComponent(
            id=_text(c.id, 20), name=_text(c.name, MAX_NAME_CHARS), kind=_choice(c.kind, ComponentKind),
            role=_text(c.role), technology=technology,
        ))
    flows = [ArchitectureFlow(source=_text(f.source, 20), target=_text(f.target, 20), data=_text(f.data)) for f in draft.flows]
    metrics = [EvaluationMetric(metric=_choice(m.metric, Metric), why=_text(m.why), goal=_text(m.goal)) for m in draft.metrics]
    tests = [SystemTest(kind=_choice(t.kind, SystemTestKind), how=_text(t.how)) for t in draft.tests]
    return TechnicalPlan(
        summary=_text(draft.summary),
        architecture=Architecture(components=components, flows=flows),
        evaluation=EvaluationPlan(metrics=metrics, tests=tests, baseline=_clean(draft.baseline) or None),
    )


def check_plan_draft(
    draft: LLMTechnicalPlanDraft, input: DesignArchitectureInput
) -> tuple[TechnicalPlan | None, str | None]:
    """Turn a draft into a TechnicalPlan, or return (None, the reason it was rejected)."""
    try:
        plan = _build(draft, known_technologies(input))
    except _Rejected as rejected:
        return None, rejected.reason
    evaluation = plan.evaluation
    texts = [plan.summary, evaluation.baseline or ""]
    texts += [t for c in plan.architecture.components for t in (c.name, c.role)]
    texts += [f.data for f in plan.architecture.flows]
    texts += [t for m in evaluation.metrics for t in (m.why, m.goal)] + [t.how for t in evaluation.tests]
    if any(len(t) > MAX_TEXT_CHARS for t in texts):
        return None, "too_long"
    if any(contains_url(t) for t in texts):
        return None, "contains_url"
    broken = plan_rule_broken(plan, uses_ai=uses_ai(input.strategy.necessity), task=input.strategy.task_type)
    if broken is not None:
        return None, broken
    return plan, None
