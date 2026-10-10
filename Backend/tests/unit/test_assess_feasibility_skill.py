"""
Tests for the assess_feasibility skill (Release 0.12, Step 2): the fact dimensions
(plain code), the model's judgement, the computed overall rating. Fake LLM only.
"""
import copy

import pytest

from app.core.brain.schemas import (
    AssessedBy,
    CostLevel,
    DatasetFit,
    EvidenceTier,
    FeasibilityDimension,
    FeasibilityLevel,
    FYPDesign,
    HardwareItem,
    HardwareKind,
    OverallFeasibility,
)
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.assess_feasibility import PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.assess_feasibility import (
    JUDGEMENT_DIMENSIONS,
    AssessFeasibilityInput,
    AssessFeasibilitySkill,
    FeasibilityPhase,
    FeasibilityRejectedError,
    LLMFeasibilityDraft,
    build_llm_input,
    check_feasibility_draft,
)
from app.domains.fyp.skills.assess_feasibility import facts
from app.domains.fyp.skills.assess_feasibility.fake import fake_feasibility
from app.domains.fyp.skills.design_architecture import LLMTechnicalPlanDraft
from app.domains.fyp.skills.design_architecture import build_llm_input as arch_llm_input
from app.domains.fyp.skills.design_architecture import check_plan_draft as check_architecture
from app.domains.fyp.skills.design_architecture.fake import fake_technical_plan
from tests.unit.test_brain_ai_strategy import ml_strategy
from tests.unit.test_brain_datasets import own_data, public
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_design_architecture_skill import arch_input, technology
from tests.unit.test_fyp_design_skills import BRIEF, GOOD_DESIGN, WS, collect, gateway_and_fake
from tests.unit.test_plan_technology_skill import MODELS


def technical_plan():
    input = arch_input()
    return check_architecture(LLMTechnicalPlanDraft(**fake_technical_plan(arch_llm_input(input))), input)[0]


def feasibility_input(tiers=(EvidenceTier.A, EvidenceTier.B), dataset=None, technology_plan=None) -> AssessFeasibilityInput:
    return AssessFeasibilityInput(
        workspace_id=WS, industry="Defense", branch="Navy", problem=BRIEF, evidence_tiers=list(tiers),
        design=FYPDesign(**GOOD_DESIGN), definition=make_definition(), strategy=ml_strategy(),
        dataset=dataset or public(1), models=MODELS, technology=technology_plan or technology(),
        technical=technical_plan(),
    )


GOOD = fake_feasibility({})


def bad(change) -> dict:
    reply = copy.deepcopy(GOOD)
    change(reply)
    return reply


def check(reply, input=None):
    return check_feasibility_draft(LLMFeasibilityDraft(**reply), input or feasibility_input())


# ── Facts (plain code) ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tiers, level", [
    ([EvidenceTier.A], FeasibilityLevel.FAVOURABLE),
    ([EvidenceTier.B, EvidenceTier.C], FeasibilityLevel.MODERATE),
    ([EvidenceTier.C], FeasibilityLevel.CONCERN),
])
def test_evidence_strength_comes_from_the_tiers(tiers, level):
    assert facts.evidence_strength(tiers).level == level


def test_data_availability_comes_from_the_dataset():
    assert facts.data_availability(feasibility_input()).level == FeasibilityLevel.FAVOURABLE
    partial = public(1, fit=DatasetFit.PARTIAL)
    assert facts.data_availability(feasibility_input(dataset=partial)).level == FeasibilityLevel.MODERATE
    generated = facts.data_availability(feasibility_input(dataset=own_data()))
    assert generated.level == FeasibilityLevel.MODERATE and generated.finding == "Data you generate"


def test_hardware_and_cost_come_from_the_essential_hardware():
    assert facts.hardware_requirement(feasibility_input()).level == FeasibilityLevel.FAVOURABLE
    assert facts.cost(feasibility_input()).level == FeasibilityLevel.FAVOURABLE
    plan = technology()
    plan.hardware.append(HardwareItem(kind=HardwareKind.JETSON, name="A Jetson board", purpose="Run the model",
                                      essential=True, cost=CostLevel.MEDIUM))
    input = feasibility_input(technology_plan=plan)
    assert facts.hardware_requirement(input).level == FeasibilityLevel.MODERATE
    assert facts.cost(input).level == FeasibilityLevel.MODERATE
    plan.hardware[-1] = plan.hardware[-1].model_copy(update={"cost": CostLevel.HIGH, "alternative": "Colab"})
    assert facts.hardware_requirement(feasibility_input(technology_plan=plan)).level == FeasibilityLevel.CONCERN


def test_evaluation_and_demonstrability_come_from_the_technical_plan():
    input = feasibility_input()
    assert facts.evaluation_possibility(input).level == FeasibilityLevel.FAVOURABLE
    assert facts.demonstrability(input).level == FeasibilityLevel.FAVOURABLE
    assert all(d.assessed_by == AssessedBy.FACTS for d in facts.fact_dimensions(input))


# ── The model's judgement ─────────────────────────────────────────────────────

def test_the_model_sees_the_facts_but_judges_only_seven_dimensions():
    shown = build_llm_input(feasibility_input())
    assert [f["dimension"] for f in shown["facts"]] == [
        "evidence_strength", "data_availability", "hardware_requirement", "cost", "evaluation_possibility", "demonstrability",
    ]
    assert len(JUDGEMENT_DIMENSIONS) == 7
    assert "Harbor Systems" not in str(shown)


def test_a_good_reply_becomes_a_full_report_with_a_computed_overall():
    report, reason = check(GOOD)
    assert reason is None
    assert [d.dimension for d in report.dimensions] == list(FeasibilityDimension)
    assert report.overall == OverallFeasibility.HIGH
    assert report.overall_reason.== "10 of 13 dimensions are favourable, 3 moderate and 0 a concern."


def test_concerns_lower_the_overall_rating():
    reply = bad(lambda r: [j.update(level="concern") for j in r["judgements"][:3]])
    report, _ = check(reply)
    assert report.overall == OverallFeasibility.LOW


@pytest.mark.parametrize("change, reason", [
    (lambda r: r["judgements"][0].update(level="great"), "unknown_choice"),
    (lambda r: r["judgements"][0].update(dimension="vibes"), "unknown_choice"),
    (lambda r: r["judgements"][0].update(dimension="cost"), "wrong_dimensions"),
    (lambda r: r["judgements"].pop(), "wrong_dimensions"),
    (lambda r: r["judgements"][0].update(reason=" "), "empty"),
    (lambda r: r["judgements"][0].update(finding="x" * 80), "too_long"),
    (lambda r: r.update(main_risks=[]), "wrong_count"),
    (lambda r: r.update(summary="Overall feasibility is High."), "states_overall"),
    (lambda r: r["main_risks"][0].update(mitigation="Read https://example.com"), "contains_url"),
])
def test_bad_replies_are_rejected(change, reason):
    report, rejected = check(bad(change))
    assert report is None and rejected == reason


async def test_the_skill_assesses_checks_and_retries_once():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r.update(main_risks=[])), GOOD])
    output, progress = await collect(AssessFeasibilitySkill(gateway), feasibility_input())
    assert output.rejection_summary == {"wrong_count": 1} and output.prompt_version == PROMPT_VERSION
    assert progress[0].phase == FeasibilityPhase.FACTS
    fake.script("fake-model", [bad(lambda r: r["judgements"].pop())] * 2)
    with pytest.raises(FeasibilityRejectedError):
        await AssessFeasibilitySkill(gateway).execute(feasibility_input())
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await AssessFeasibilitySkill(gateway).execute(feasibility_input())


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    output = await registry.get("assess_feasibility").execute(feasibility_input())
    assert output.report.overall in set(OverallFeasibility)
