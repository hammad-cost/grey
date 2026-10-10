"""
Tests for the generate_proposal skill (Release 0.14, Step 2): the code-built
sections and references, the model's narrative sections (fake LLM), rewrites,
and the Markdown export.
"""
import pytest

from app.core.brain.proposal_rules import MODEL_SECTIONS, proposal_rule_broken
from app.core.brain.schemas import ProposalSectionId, WrittenBy
from app.core.config.settings import Settings
from app.core.llm import WRITING, LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.generate_proposal import PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.generate_proposal import (
    SECTION_GROUPS,
    GenerateProposalInput,
    GenerateProposalSkill,
    LLMSectionsDraft,
    ProposalPhase,
    ProposalRejectedError,
    build_context,
    check_sections_draft,
    proposal_markdown,
)
from app.domains.fyp.skills.generate_proposal.builders import assemble, code_sections, references
from app.domains.fyp.skills.generate_proposal.fake import fake_sections, install_fake_answers
from tests.unit.test_fyp_design_skills import collect, gateway_and_fake
from tests.unit.test_prepare_supervisor_brief_skill import brief_input

S = ProposalSectionId


def proposal_gateway():
    """A fake-mode gateway that answers the proposal sections (scripted replies still come first)."""
    gateway, fake = gateway_and_fake()
    install_fake_answers(gateway)
    return gateway, fake


def decisions():
    return brief_input()


def group_reply(group, **changes) -> dict:
    reply = fake_sections({**build_context(decisions()), "sections_to_write": [s.value for s in group]})
    for section in reply["sections"]:
        section.update(changes.get(section["id"], {}))
    return reply


def check(reply, wanted, refs=1):
    return check_sections_draft(LLMSectionsDraft(**reply), wanted, refs, str(build_context(decisions())))


# ── Built in code ─────────────────────────────────────────────────────────────

def test_code_sections_come_straight_from_approved_decisions():
    d = decisions()
    built = code_sections(d)
    assert set(built) == set(S) - set(MODEL_SECTIONS)
    assert all(s.written_by == WrittenBy.GREY and s.sources for s in built.values())
    assert built[S.PROJECT_TITLE].paragraphs == [d.design.title]
    assert built[S.FUNCTIONAL_REQUIREMENTS].items[0].startswith("FR1: Core 0")
    assert any(i.startswith("Out of scope — Out 0") for i in built[S.SCOPE].items)
    assert built[S.DATASET].paragraphs[0].startswith("Vessel tracks dataset 1 — public dataset")
    assert any(i.startswith("Link: https://") for i in built[S.DATASET].items)
    assert built[S.TIMELINE].items[0].startswith("Month 1")
    assert built[S.RISKS].paragraphs[0].startswith("Overall feasibility: High")


def test_references_are_the_verified_evidence():
    d = decisions()
    refs = references(d)
    assert [r.number for r in refs] == list(range(1, len(d.evidence) + 1))
    assert refs[0].url == d.evidence[0].url
    assert code_sections(d)[S.REFERENCES].items[0].startswith("[1] ")


# ── Written by the model ──────────────────────────────────────────────────────

def test_the_model_writes_from_the_context_with_numbered_evidence():
    context = build_context(decisions())
    assert context["evidence"][0]["number"] == 1
    assert "https://" not in str(context)
    assert [len(g) for g in SECTION_GROUPS] == [5, 4, 2]
    assert sorted(s for g in SECTION_GROUPS for s in g) == sorted(MODEL_SECTIONS)


def test_a_good_group_becomes_sections_with_sources():
    sections, reason = check(group_reply(SECTION_GROUPS[0]), SECTION_GROUPS[0])
    assert reason is None and set(sections) == set(SECTION_GROUPS[0])
    assert sections[S.REAL_WORLD_EVIDENCE].sources == ["Verified evidence sources"]
    assert all(s.written_by == WrittenBy.MODEL for s in sections.values())


@pytest.mark.parametrize("group, change, reason", [
    (0, {"introduction": {"id": "conclusion"}}, "unknown_choice"),
    (0, {"introduction": {"id": "aim"}}, "wrong_sections"),
    (0, {"introduction": {"paragraphs": []}}, "wrong_count"),
    (0, {"introduction": {"paragraphs": ["a", "b", "c", "d"]}}, "wrong_count"),
    (0, {"introduction": {"items": ["x"]}}, "wrong_count"),
    (1, {"objectives": {"items": ["Only one."]}}, "wrong_count"),
    (0, {"introduction": {"paragraphs": [" "]}}, "empty"),
    (0, {"introduction": {"paragraphs": ["x" * 1500]}}, "too_long"),
    (0, {"introduction": {"paragraphs": ["See https://example.com"]}}, "contains_url"),
    (0, {"introduction": {"paragraphs": ["As shown in [4]."]}}, "unknown_citation"),
    (0, {"introduction": {"paragraphs": ["Errors drop by 40%."]}}, "invented_number"),
])
def test_bad_replies_are_rejected(group, change, reason):
    sections, rejected = check(group_reply(SECTION_GROUPS[group], **change), SECTION_GROUPS[group])
    assert sections is None and rejected == reason


def test_a_missing_section_is_rejected():
    reply = group_reply(SECTION_GROUPS[0])
    reply["sections"].pop()
    assert check(reply, SECTION_GROUPS[0])[1] == "wrong_sections"


# ── Running the skill ─────────────────────────────────────────────────────────

async def test_the_skill_builds_writes_and_assembles_a_consistent_proposal():
    gateway, fake = proposal_gateway()
    output, progress = await collect(GenerateProposalSkill(gateway), GenerateProposalInput(decisions=decisions()))
    proposal = output.proposal
    assert proposal_rule_broken(proposal) is None
    assert [s.id for s in proposal.sections] == list(S)
    assert len(fake.calls) == 3                                     # three small calls, not one big prompt
    assert output.prompt_version == PROMPT_VERSION
    assert [p.phase for p in progress] == [ProposalPhase.BUILDING] + [ProposalPhase.WRITING] * 3 + [ProposalPhase.CHECKING]


async def test_the_skill_uses_the_writing_profile_and_retries_once():
    gateway, fake = proposal_gateway()
    bad = group_reply(SECTION_GROUPS[0], introduction={"paragraphs": ["See [9]."]})
    fake.script("fake-model", [bad, group_reply(SECTION_GROUPS[0])])
    output = await GenerateProposalSkill(gateway).execute(GenerateProposalInput(decisions=decisions()))
    assert output.rejection_summary == {"unknown_citation": 1}
    assert WRITING == "writing"

    fake.script("fake-model", [bad, bad])
    with pytest.raises(ProposalRejectedError):
        await GenerateProposalSkill(gateway).execute(GenerateProposalInput(decisions=decisions()))
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await GenerateProposalSkill(gateway).execute(GenerateProposalInput(decisions=decisions()))


async def test_a_rewrite_changes_only_one_section():
    gateway, fake = proposal_gateway()
    first = (await GenerateProposalSkill(gateway).execute(GenerateProposalInput(decisions=decisions()))).proposal
    calls_before = len(fake.calls)
    output, progress = await collect(GenerateProposalSkill(gateway), GenerateProposalInput(
        decisions=decisions(), rewrite_section=S.INTRODUCTION, previous=first,
    ))
    second = output.proposal
    assert len(fake.calls) == calls_before + 1
    assert "current_text" in fake.calls[-1].input_json
    changed = [a.id for a, b in zip(first.sections, second.sections) if a != b]
    assert changed == [S.INTRODUCTION]
    assert "(rewritten)" in second.sections[1].paragraphs[0]
    assert progress[1].label == "Rewriting Introduction"


def test_the_markdown_export_has_every_section_and_its_sources():
    d = decisions()
    model_sections = {}
    for group in SECTION_GROUPS:
        model_sections.update(check(group_reply(group), group)[0])
    text = proposal_markdown(assemble(d, model_sections))
    assert text.startswith(f"# {d.design.title}\n")
    assert "## Introduction" in text and "## References" in text and "## Project Title" not in text
    assert "*Source: Verified evidence sources*" in text
    assert "1. Build Core 0." in text                                # objectives are numbered


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    output = await registry.get("generate_proposal").execute(GenerateProposalInput(decisions=decisions()))
    assert len(output.proposal.sections) == 23
