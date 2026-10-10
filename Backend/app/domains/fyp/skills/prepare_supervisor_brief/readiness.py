"""
The supervisor readiness checks (blueprint §33) and the supervisor-ready summary
(blueprint §34) — plain code, no AI, built only from approved decisions.

Each check either passes or "needs attention" with what to do. Grey can't send
the student back to an earlier stage yet, so a weakness is something to resolve
or discuss with the supervisor.
"""
from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import (
    AINecessity,
    DatasetKind,
    EvidenceTier,
    FeasibilityDimension,
    FeasibilityLevel,
    ReadinessCheck,
    ReadinessCheckId,
    ReadinessStatus,
    ScopeKind,
    SummaryItem,
)
from app.domains.fyp.skills.prepare_supervisor_brief.schemas import SupervisorBriefInput

QUESTIONS = {
    ReadinessCheckId.PROBLEM_CLEAR: "Is the problem clear?",
    ReadinessCheckId.EVIDENCE_SUPPORTED: "Is the problem supported by evidence?",
    ReadinessCheckId.CONTRIBUTION_CLEAR: "Is the proposed contribution clear?",
    ReadinessCheckId.DATASET_AVAILABLE: "Is the dataset available?",
    ReadinessCheckId.AI_JUSTIFIED: "Is the AI strategy justified?",
    ReadinessCheckId.SCOPE_REALISTIC: "Is the scope realistic?",
    ReadinessCheckId.TECHNOLOGY_ACCESSIBLE: "Is the technology accessible?",
    ReadinessCheckId.EVALUATION_POSSIBLE: "Is evaluation possible?",
    ReadinessCheckId.RISKS_UNDERSTOOD: "Are the main risks understood?",
}

NECESSITY_WORDS = {
    AINecessity.AI_NECESSARY: "AI is necessary",
    AINecessity.AI_OPTIONAL: "AI is useful but optional",
    AINecessity.TRADITIONAL_ML: "Traditional machine learning is enough",
    AINecessity.RULE_BASED: "A rule-based approach is better",
    AINecessity.OPTIMIZATION: "Optimization fits better than AI",
    AINecessity.EXISTING_MODEL: "An existing model or service is enough",
    AINecessity.NOT_REQUIRED: "AI is not required",
}
DATASET_KIND_WORDS = {
    DatasetKind.PUBLIC: "public dataset",
    DatasetKind.SYNTHETIC: "data you generate",
    DatasetKind.STUDENT_COLLECTED: "data you collect",
}


def _check(check: ReadinessCheckId, ok: bool, passed: str, attention: str) -> ReadinessCheck:
    return ReadinessCheck(
        check=check, question=QUESTIONS[check],
        status=ReadinessStatus.PASS if ok else ReadinessStatus.ATTENTION,
        detail=passed if ok else attention,
    )


def _level(input: SupervisorBriefInput, dimension: FeasibilityDimension) -> FeasibilityLevel:
    return next(d.level for d in input.feasibility.dimensions if d.dimension == dimension)


def _not_concern(input: SupervisorBriefInput, *dimensions: FeasibilityDimension) -> bool:
    return all(_level(input, d) != FeasibilityLevel.CONCERN for d in dimensions)


def readiness_checks(input: SupervisorBriefInput) -> list[ReadinessCheck]:
    """The nine readiness checks, in the blueprint's order."""
    problem = input.definition.problem_definition
    tiers = [source.evidence_tier for source in input.evidence]
    strong = sum(1 for t in tiers if t in (EvidenceTier.A, EvidenceTier.B))
    core = [i for i in input.definition.scope if i.kind == ScopeKind.CORE]
    risks = input.feasibility.main_risks
    F = FeasibilityDimension
    return [
        _check(ReadinessCheckId.PROBLEM_CLEAR, bool(problem.problem_statement and problem.gap),
               "The problem statement and the gap it leaves are written down.",
               "Write the problem statement and the gap in one sentence each before the meeting."),
        _check(ReadinessCheckId.EVIDENCE_SUPPORTED, strong > 0,
               f"{strong} strong source{'s' if strong != 1 else ''} (Tier A or B) support the problem.",
               "Only discovery-level sources support the problem; find a primary source before the meeting."),
        _check(ReadinessCheckId.CONTRIBUTION_CLEAR, bool(input.design.main_contribution) and _not_concern(input, F.NOVELTY),
               input.design.main_contribution,
               "The contribution looks weak next to what exists; agree a sharper contribution with your supervisor."),
        _check(ReadinessCheckId.DATASET_AVAILABLE, _not_concern(input, F.DATA_AVAILABILITY),
               f"{input.dataset.name} ({DATASET_KIND_WORDS[input.dataset.kind]}).",
               "Getting the data is a concern; confirm access or a fallback before you commit."),
        _check(ReadinessCheckId.AI_JUSTIFIED, bool(input.strategy.necessity_reason),
               f"{NECESSITY_WORDS[input.strategy.necessity]}: {input.strategy.necessity_reason}",
               "Explain why the project does or doesn't need AI."),
        _check(ReadinessCheckId.SCOPE_REALISTIC,
               2 <= len(core) <= 8 and _not_concern(input, F.TIME, F.TECHNICAL_COMPLEXITY),
               f"{len(core)} core features fit the timeline and your skills.",
               "Time or technical complexity is a concern; ask your supervisor which core feature to cut."),
        _check(ReadinessCheckId.TECHNOLOGY_ACCESSIBLE, _not_concern(input, F.HARDWARE_REQUIREMENT, F.COST),
               "The tools and hardware are free or already available.",
               "Some essential hardware or services are expensive; confirm the cheaper alternative."),
        _check(ReadinessCheckId.EVALUATION_POSSIBLE, _not_concern(input, F.EVALUATION_POSSIBILITY),
               f"{len(input.technical.evaluation.metrics)} metric(s) and {len(input.technical.evaluation.tests)} test(s) are planned.",
               "Plan how you will measure success before the meeting."),
        _check(ReadinessCheckId.RISKS_UNDERSTOOD, bool(risks) and all(r.mitigation for r in risks),
               f"{len(risks)} main risk(s), each with a mitigation.",
               "List the main risks and what you will do about each."),
    ]


def supervisor_summary(input: SupervisorBriefInput) -> list[SummaryItem]:
    """The compact briefing (blueprint §34), every line taken from an approved decision."""
    strategy, technical = input.strategy, input.technical
    evidence = "; ".join(f"{s.title} ({s.organization}, Tier {s.evidence_tier.value})" for s in input.evidence[:3])
    ai = NECESSITY_WORDS[strategy.necessity]
    if uses_ai(strategy.necessity) and strategy.task_type and strategy.primary_strategy:
        ai += f" — {strategy.task_type.value.replace('_', ' ')}, {strategy.primary_strategy.approach.value.replace('_', ' ')}"
    order = {c.id: c.name for c in technical.architecture.components}
    metrics = ", ".join(m.metric.value.replace("_", " ") for m in technical.evaluation.metrics)
    tests = ", ".join(t.kind.value.replace("_", " ") for t in technical.evaluation.tests)
    items = [
        ("Project title", input.design.title),
        ("Industry", f"{input.industry} → {input.branch}"),
        ("Functional area", f"{input.area.functional_area} → {input.area.specific_area}"),
        ("Real-world problem", input.problem.real_world_problem),
        ("Evidence", evidence or "No sources recorded"),
        ("Proposed solution", input.design.summary),
        ("Contribution", input.design.main_contribution),
        ("Dataset", f"{input.dataset.name} ({DATASET_KIND_WORDS[input.dataset.kind]}, {input.dataset.source})"),
        ("AI / ML strategy", ai),
        ("Technology stack", ", ".join(f"{c.area.value.replace('_', ' / ')}: {c.choice}" for c in input.technology.stack)),
        ("Architecture", " → ".join(order.values())),
        ("Evaluation", "; ".join(x for x in (metrics, tests) if x)),
        ("Feasibility", f"{input.feasibility.overall.value.capitalize()} — {input.feasibility.overall_reason}"),
        ("Main risks", "; ".join(r.risk for r in input.feasibility.main_risks)),
    ]
    return [SummaryItem(label=label, value=value) for label, value in items]
