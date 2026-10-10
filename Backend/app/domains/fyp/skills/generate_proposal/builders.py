"""
The proposal sections Grey builds in plain code, straight from approved
decisions in the Project Brain (blueprint §37 traceability) — no AI, so they
can't drift from what the student approved:

  project title, scope, functional requirements, dataset, AI / ML approach,
  technology stack, system architecture, hardware, evaluation plan, risks,
  timeline, and the references (the verified evidence sources).
"""
from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import (
    ComponentKind,
    Proposal,
    ProposalReference,
    ProposalSection,
    ProposalSectionId,
    ScopeKind,
    WrittenBy,
)
from app.domains.fyp.skills.generate_proposal.schemas import SECTION_TITLES
from app.domains.fyp.skills.prepare_supervisor_brief import SupervisorBriefInput
from app.domains.fyp.skills.prepare_supervisor_brief.readiness import DATASET_KIND_WORDS, NECESSITY_WORDS

S = ProposalSectionId


def _words(value: str) -> str:
    return value.replace("_", " ")


def _section(id: ProposalSectionId, sources: list[str], paragraphs=(), items=()) -> ProposalSection:
    return ProposalSection(id=id, title=SECTION_TITLES[id], paragraphs=list(paragraphs), items=list(items),
                           sources=sources, written_by=WrittenBy.GREY)


def references(d: SupervisorBriefInput) -> list[ProposalReference]:
    """The verified evidence behind the chosen problem, numbered in order."""
    return [
        ProposalReference(
            number=n, title=s.title, organization=s.organization, url=s.url,
            published=s.published_date.isoformat() if s.published_date else None,
            source_type=s.source_type.value,
        )
        for n, s in enumerate(d.evidence, start=1)
    ]


def _scope(d: SupervisorBriefInput) -> ProposalSection:
    labels = {ScopeKind.CORE: "Core", ScopeKind.OPTIONAL: "Optional", ScopeKind.OUT_OF_SCOPE: "Out of scope"}
    items = [f"{labels[i.kind]} — {i.title}: {i.description}" for kind in labels for i in d.definition.scope if i.kind == kind]
    return _section(S.SCOPE, ["Approved scope"],
                    ["Core features will be built; optional features only if time allows; out-of-scope features are excluded."],
                    items)


def _requirements(d: SupervisorBriefInput) -> ProposalSection:
    features = [i for i in d.definition.scope if i.kind in (ScopeKind.CORE, ScopeKind.OPTIONAL)]
    items = [
        f"FR{n}{' (optional)' if i.kind == ScopeKind.OPTIONAL else ''}: {i.title} — {i.description}"
        for n, i in enumerate(features, start=1)
    ]
    return _section(S.FUNCTIONAL_REQUIREMENTS, ["Approved scope"], [], items)


def _dataset(d: SupervisorBriefInput) -> ProposalSection:
    o = d.dataset
    items = [f"Size: {o.size}", f"Main features: {', '.join(o.main_features)}", f"Labels: {o.labels}",
             f"License: {o.license}", f"Preparation: {'; '.join(o.preprocessing)}", f"Limitations: {'; '.join(o.limitations)}"]
    if o.how_to_get:
        items.insert(0, f"How the data is obtained: {o.how_to_get}")
    if o.url:
        items.append(f"Link: {o.url}")
    paragraph = f"{o.name} — {DATASET_KIND_WORDS[o.kind]}, from {o.source}. {o.relevance}"
    return _section(S.DATASET, ["Selected dataset (dataset discovery)"], [paragraph], items)


def _ai_approach(d: SupervisorBriefInput) -> ProposalSection:
    s = d.strategy
    paragraphs = [f"{NECESSITY_WORDS[s.necessity]}. {s.necessity_reason}", f"Without AI: {s.without_ai}"]
    items: list[str] = []
    if uses_ai(s.necessity):
        if s.ai_component:
            items.append(f"Where AI is used: {s.ai_component}")
        if s.task_type:
            items.append(f"AI task: {_words(s.task_type.value)}")
        if s.primary_strategy:
            items.append(f"Main approach: {_words(s.primary_strategy.approach.value)} — {s.primary_strategy.reason}")
        if s.fallback_strategy:
            items.append(f"Fallback: {_words(s.fallback_strategy.approach.value)} — {s.fallback_strategy.reason}")
    items += [f"Ready-made option: {o.name} ({_words(o.kind.value)}) — {_words(o.use.value)}: {o.reason}" for o in d.models.options]
    items.append(f"Model plan: {d.models.summary}")
    return _section(S.AI_ML_APPROACH, ["Approved AI strategy", "Approved model plan"], paragraphs, items)


def _technology(d: SupervisorBriefInput) -> ProposalSection:
    items = [f"{_words(c.area.value).replace('ai ml', 'AI / ML').capitalize()}: {c.choice} — {c.reason}" for c in d.technology.stack]
    return _section(S.TECHNOLOGY_STACK, ["Approved technology plan"], [d.technology.summary], items)


def _architecture(d: SupervisorBriefInput) -> ProposalSection:
    a = d.technical.architecture
    names = {c.id: c.name for c in a.components}
    items = [f"{c.name} ({_words(c.kind.value)}): {c.role}{f' [{c.technology}]' if c.technology else ''}" for c in a.components]
    flows = "; ".join(f"{names[f.source]} → {names[f.target]} ({f.data})" for f in a.flows)
    return _section(S.SYSTEM_ARCHITECTURE, ["Approved architecture"], [d.technical.summary, f"Data flow: {flows}."], items)


def _hardware(d: SupervisorBriefInput) -> ProposalSection:
    items = [
        f"{h.name} — {h.purpose} ({'essential' if h.essential else 'nice to have'}, {h.cost.value} cost)"
        + (f"; alternative: {h.alternative}" if h.alternative else "")
        for h in d.technology.hardware
    ]
    return _section(S.HARDWARE_REQUIREMENTS, ["Approved technology plan"], [], items)


def _evaluation(d: SupervisorBriefInput) -> ProposalSection:
    e = d.technical.evaluation
    items = [f"{_words(m.metric.value).upper() if len(m.metric.value) <= 4 else _words(m.metric.value).capitalize()}: {m.goal} — {m.why}" for m in e.metrics]
    items += [f"{_words(t.kind.value).capitalize()}: {t.how}" for t in e.tests]
    if e.baseline:
        items.append(f"Baseline: {e.baseline}")
    return _section(S.EVALUATION_PLAN, ["Approved evaluation plan"], [], items)


def _risks(d: SupervisorBriefInput) -> ProposalSection:
    f = d.feasibility
    return _section(S.RISKS, ["Accepted feasibility report"],
                    [f"Overall feasibility: {f.overall.value.capitalize()} — {f.overall_reason}"],
                    [f"{r.risk} — mitigation: {r.mitigation}" for r in f.main_risks])


def _timeline(d: SupervisorBriefInput) -> ProposalSection:
    has_model = any(c.kind == ComponentKind.MODEL for c in d.technical.architecture.components)
    core = [i.title for i in d.definition.scope if i.kind == ScopeKind.CORE]
    metrics = ", ".join(_words(m.metric.value) for m in d.technical.evaluation.metrics) or "the system tests"
    items = [
        "Month 1: Literature review, requirements and supervisor sign-off.",
        f"Month 2: Data preparation — {d.dataset.name}.",
        f"Months 3–4: Build the {'AI model and its baseline' if has_model else 'core logic'}.",
        f"Months 4–5: Build the core features — {', '.join(core)}.",
        "Month 6: Integration and system testing.",
        f"Month 7: Evaluation ({metrics}).",
        "Month 8: Final report, demonstration and presentation.",
    ]
    return _section(S.TIMELINE, ["Approved scope", "Approved evaluation plan", "Accepted feasibility report"],
                    ["A plan for about eight months; adjust the months to your university's calendar."], items)


def _references(refs: list[ProposalReference]) -> ProposalSection:
    items = [
        f"[{r.number}] {r.title} — {r.organization}{f' ({r.published})' if r.published else ''}. {r.url}" for r in refs
    ] or ["No sources were recorded."]
    return _section(S.REFERENCES, ["Verified evidence sources"], [], items)


def code_sections(d: SupervisorBriefInput) -> dict[ProposalSectionId, ProposalSection]:
    """Every section Grey builds in code, keyed by id."""
    refs = references(d)
    return {
        S.PROJECT_TITLE: _section(S.PROJECT_TITLE, ["Approved FYP design"], [d.design.title]),
        S.SCOPE: _scope(d),
        S.FUNCTIONAL_REQUIREMENTS: _requirements(d),
        S.DATASET: _dataset(d),
        S.AI_ML_APPROACH: _ai_approach(d),
        S.TECHNOLOGY_STACK: _technology(d),
        S.SYSTEM_ARCHITECTURE: _architecture(d),
        S.HARDWARE_REQUIREMENTS: _hardware(d),
        S.EVALUATION_PLAN: _evaluation(d),
        S.RISKS: _risks(d),
        S.TIMELINE: _timeline(d),
        S.REFERENCES: _references(refs),
    }


def assemble(d: SupervisorBriefInput, model_sections: dict[ProposalSectionId, ProposalSection]) -> Proposal:
    """The full proposal: every section in the blueprint's order."""
    sections = {**code_sections(d), **model_sections}
    return Proposal(title=d.design.title, sections=[sections[s] for s in ProposalSectionId], references=references(d))
