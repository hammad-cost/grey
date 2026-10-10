"""
GenerateProposalSkill — writes the FYP proposal from the Project Brain
(product blueprint §36–37, Release 0.14).

  builders.py (code)        — 12 sections built straight from approved decisions,
                              including the references (the verified evidence)
  LLMGateway ("writing")    — the 11 narrative sections, in three small calls
                              (never one large prompt)
  check_sections_draft      — rejects replies that cite unknown sources, invent
                              percentages, contain links, or skip a section

A rewrite regenerates one narrative section and keeps everything else. One retry
per call, then ProposalRejectedError. The skill never reads or writes the database.
"""
from collections import Counter

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import ProposalSection, ProposalSectionId, ScopeKind
from app.core.llm import WRITING, LLMGateway, LLMRequest
from app.core.skills.base import Skill, SkillMetadata
from app.domains.fyp.prompts.generate_proposal import INSTRUCTIONS, PROMPT_VERSION, REWRITE_REQUEST
from app.domains.fyp.skills.fyp_design_shared import brief_for_model
from app.domains.fyp.skills.generate_proposal.builders import assemble, references
from app.domains.fyp.skills.generate_proposal.schemas import (
    SECTION_GROUPS,
    SECTION_TITLES,
    GenerateProposalInput,
    GenerateProposalOutput,
    LLMSectionsDraft,
    ProposalPhase,
    ProposalProgress,
    ProposalProgressCallback,
)
from app.domains.fyp.skills.generate_proposal.validation import check_sections_draft
from app.domains.fyp.skills.prepare_supervisor_brief import SupervisorBriefInput
from app.domains.fyp.skills.prepare_supervisor_brief.readiness import supervisor_summary

MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 4_000

BUILDING_LABEL = "Building sections from your approved decisions"
GROUP_LABELS = [
    "Writing the introduction, background and evidence",
    "Writing the solution, aim, objectives and method",
    "Writing the expected outcomes and limitations",
]
CHECKING_LABEL = "Checking citations and consistency"


class ProposalRejectedError(Exception):
    """The model's sections failed Grey's checks twice."""

    def __init__(self, message: str, rejection_summary: dict[str, int]) -> None:
        super().__init__(message)
        self.rejection_summary = rejection_summary


def build_context(d: SupervisorBriefInput) -> dict:
    """The approved decisions the model writes from (no links)."""
    definition = d.definition.problem_definition
    return {
        "summary": [{"label": i.label, "value": i.value} for i in supervisor_summary(d)],
        "problem": brief_for_model(d.problem),
        "problem_definition": definition.model_dump(mode="json"),
        "evidence": [
            {"number": r.number, "title": r.title, "organization": r.organization,
             "point": d.evidence[r.number - 1].supporting_point}
            for r in references(d)
        ],
        "design": {"title": d.design.title, "summary": d.design.summary, "target_user": d.design.target_user,
                   "main_contribution": d.design.main_contribution},
        "core_features": [i.title for i in d.definition.scope if i.kind == ScopeKind.CORE],
        "out_of_scope": [i.title for i in d.definition.scope if i.kind == ScopeKind.OUT_OF_SCOPE],
        "uses_ai": uses_ai(d.strategy.necessity),
        "dataset_limitations": d.dataset.limitations,
        "evaluation_goals": [{"metric": m.metric.value, "goal": m.goal} for m in d.technical.evaluation.metrics],
        "main_risks": [r.risk for r in d.feasibility.main_risks],
    }


class GenerateProposalSkill(Skill):
    metadata = SkillMetadata(
        name="generate_proposal",
        description=(
            "Write the FYP proposal from the Project Brain: fact sections and references built in code, "
            "narrative sections written in small model calls, every section traceable to approved decisions."
        ),
        version="0.14.0",
    )

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def _write(self, wanted, context: dict, reference_count: int, report, label: str, rewrite=None):
        """Write one group of narrative sections (or one section for a rewrite), with one retry."""
        llm_input = {**context, "sections_to_write": [s.value for s in wanted]}
        if rewrite is not None:
            llm_input["rewrite"] = rewrite
        context_text = str(context)
        rejections: Counter = Counter()
        for _ in range(MAX_ATTEMPTS):
            await report(ProposalPhase.WRITING, label)
            result = await self._llm.generate_structured(LLMRequest(
                skill=self.metadata.name,
                profile=WRITING,
                instructions=INSTRUCTIONS,
                input=llm_input,
                output_schema=LLMSectionsDraft,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ))
            sections, reason = check_sections_draft(result.output, wanted, reference_count, context_text)
            if sections is not None:
                return sections, result, rejections
            rejections[reason] += 1
            llm_input = {**llm_input, "feedback_from_previous_attempt": (
                f"Your answer broke a rule: {reason}. Write exactly the sections in sections_to_write, each once; "
                "1-3 paragraphs each (objectives: 3-6 items, no paragraphs); cite only listed evidence numbers as "
                "[n]; never invent percentages; no links; keep paragraphs short."
            )}
        raise ProposalRejectedError("The proposal sections failed Grey's checks twice.", dict(rejections))

    async def execute(
        self,
        input: GenerateProposalInput,
        on_progress: ProposalProgressCallback | None = None,
    ) -> GenerateProposalOutput:
        """
        Write the proposal, or rewrite one narrative section of it.

        Raises:
            ProposalRejectedError: a call's reply failed the checks twice.
            LLMError subclasses:   the gateway could not get an answer.
        """
        async def report(phase: ProposalPhase, label: str) -> None:
            if on_progress is not None:
                await on_progress(ProposalProgress(phase=phase, label=label))

        d = input.decisions
        await report(ProposalPhase.BUILDING, BUILDING_LABEL)
        context = build_context(d)
        reference_count = len(d.evidence)
        rejections: Counter = Counter()
        model_sections: dict[ProposalSectionId, ProposalSection] = {}
        result = None

        if input.rewrite_section is not None and input.previous is not None:
            section_id = input.rewrite_section
            current = next(s for s in input.previous.sections if s.id == section_id)
            model_sections = {s.id: s for s in input.previous.sections if s.written_by.value == "model"}
            written, result, rejected = await self._write(
                [section_id], context, reference_count, report, f"Rewriting {SECTION_TITLES[section_id]}",
                rewrite={"student_request": REWRITE_REQUEST,
                         "current_text": {"paragraphs": current.paragraphs, "items": current.items}},
            )
            model_sections.update(written)
            rejections.update(rejected)
        else:
            for group, label in zip(SECTION_GROUPS, GROUP_LABELS):
                written, result, rejected = await self._write(group, context, reference_count, report, label)
                model_sections.update(written)
                rejections.update(rejected)

        await report(ProposalPhase.CHECKING, CHECKING_LABEL)
        return GenerateProposalOutput(
            proposal=assemble(d, model_sections),
            provider=result.provider,
            model=result.model,
            prompt_version=PROMPT_VERSION,
            rejection_summary=dict(rejections),
        )
