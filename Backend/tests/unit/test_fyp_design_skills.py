"""
Tests for the Release 0.5 skills (Step 2): classify_area and design_fyp.

Covers what each skill sends the model, how bad replies are rejected (links,
organization names, named technologies, unchanged redesigns…), the one
retry, the fake-mode answers, and registration in the Skill Registry.

The model is always FakeLLMProvider (scripted per test). No network, no keys.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.core.brain.schemas import (
    EvidenceStrength,
    EvidenceTier,
    FunctionalArea,
    FYPAdjustment,
    FYPDesign,
    ProblemSourceDetail,
    ProblemStatus,
    ProblemTaskType,
    SourceType,
    StoredProblemCandidate,
)
from app.core.config.settings import Settings
from app.core.llm import FAST_CHEAP, STRUCTURED_REASONING, LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.classify_area import PROMPT_VERSION as AREA_PROMPT_VERSION
from app.domains.fyp.prompts.design_fyp import ADJUSTMENT_REQUESTS
from app.domains.fyp.prompts.design_fyp import PROMPT_VERSION as DESIGN_PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.classify_area import AreaRejectedError, ClassifyAreaInput, ClassifyAreaSkill
from app.domains.fyp.skills.classify_area.fake import fake_area
from app.domains.fyp.skills.design_fyp import (
    DesignFYPInput,
    DesignFYPSkill,
    DesignRejectedError,
    build_llm_input,
)
from app.domains.fyp.skills.design_fyp.fake import fake_design
from app.domains.fyp.skills.fyp_design_shared import (
    DesignPhase,
    brief_for_model,
    brief_from_problem,
    named_technology,
)

WS = "ws-navy"


# ── Helpers ───────────────────────────────────────────────────────────────────

def stored_problem() -> StoredProblemCandidate:
    return StoredProblemCandidate(
        id="p-1", workspace_id=WS, problem_run_id="pr-1", rank=1, status=ProblemStatus.SELECTED,
        title="Abnormal vessel movement detection",
        real_world_problem="Operators must monitor large volumes of vessel data by hand.",
        observed_solutions="Companies are building automated maritime surveillance platforms.",
        technical_problem="Detecting anomalous trajectories in vessel position time series.",
        task_type=ProblemTaskType.ANOMALY_DETECTION,
        why_it_matters="Earlier detection improves maritime awareness.",
        possible_fyp_direction="Build a model that flags unusual vessel tracks in public data.",
        evidence=[ProblemSourceDetail(
            evidence_source_id="ev-1", supporting_point="Operators review vessel data manually.",
            title="Harbor report", organization="Harbor Systems (sample company)",
            url="https://harbor.example/report", source_type=SourceType.COMPANY,
            evidence_tier=EvidenceTier.A, published_date=date(2026, 1, 1),
        )],
        evidence_strength=EvidenceStrength(tier_a=1),
    )


BRIEF = brief_from_problem(stored_problem())
AREA = FunctionalArea(functional_area="Maritime Surveillance", specific_area="Vessel Behavior Monitoring",
                      explanation="The problem is about how ships move.")

GOOD_AREA = {"functional_area": "Maritime Surveillance", "specific_area": "Vessel Behavior Monitoring",
             "explanation": "The problem is about how ships move."}
GOOD_DESIGN = {
    "title": "Explainable alerts for unusual vessel movements",
    "summary": "A web tool that flags unusual vessel tracks and explains each alert.",
    "target_user": "Coastal monitoring analysts",
    "system_input": "Vessel position reports over time",
    "system_output": "A ranked list of unusual tracks with reasons",
    "main_contribution": "Alerts an analyst can check in seconds.",
    "scope_reduction": "One student builds only the alerting part of a surveillance system.",
}


def gateway_and_fake():
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    return gateway, gateway.router.provider("fake")


def area_input() -> ClassifyAreaInput:
    return ClassifyAreaInput(workspace_id=WS, industry="Defense", branch="Navy", problem=BRIEF)


def design_input(**overrides) -> DesignFYPInput:
    fields = dict(workspace_id=WS, industry="Defense", branch="Navy", area=AREA, problem=BRIEF)
    fields.update(overrides)
    return DesignFYPInput(**fields)


def redesign_input(adjustment=FYPAdjustment.MAKE_SIMPLER, note=None) -> DesignFYPInput:
    return design_input(adjustment=adjustment, note=note, previous_design=FYPDesign(**GOOD_DESIGN))


async def collect(skill, input):
    seen = []

    async def on_progress(progress):
        seen.append(progress)

    output = await skill.execute(input, on_progress=on_progress)
    return output, seen


# ── Problem brief ─────────────────────────────────────────────────────────────

def test_brief_carries_the_problem_and_its_evidence_points():
    assert BRIEF.title == "Abnormal vessel movement detection"
    assert BRIEF.evidence_points == ["Operators review vessel data manually."]
    assert BRIEF.organizations == ["Harbor Systems (sample company)"]


def test_the_model_never_sees_organizations_urls_or_ids():
    shown = str(brief_for_model(BRIEF))
    assert "Harbor Systems" not in shown
    assert "harbor.example" not in shown and "ev-1" not in shown and "p-1" not in shown


@pytest.mark.parametrize("text, found", [
    ("Train a model with PyTorch", "PyTorch"),
    ("Deploy it on AWS", "AWS"),
    ("Use the Kaggle credit card data", "Kaggle"),
    ("Analysts react to alerts quickly", None),
    ("A dashboard for budget planning", None),
])
def test_named_technology_spots_named_tools_only(text, found):
    assert named_technology(text) == found


# ── classify_area ─────────────────────────────────────────────────────────────

async def test_area_is_classified_with_the_fast_profile():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_AREA])

    output, progress = await collect(ClassifyAreaSkill(gateway), area_input())

    assert output.area.functional_area == "Maritime Surveillance"
    assert (output.provider, output.model, output.prompt_version) == ("fake", "fake-model", AREA_PROMPT_VERSION)
    assert [p.phase for p in progress] == [DesignPhase.CLASSIFYING_AREA]
    assert gateway.router.profile(FAST_CHEAP) is not None
    assert "Harbor Systems" not in fake.calls[0].input_json


@pytest.mark.parametrize("bad, reason", [
    ({**GOOD_AREA, "functional_area": "Navy"}, "same_as_branch"),
    ({**GOOD_AREA, "specific_area": "maritime surveillance"}, "specific_same_as_functional"),
    ({**GOOD_AREA, "explanation": "See https://navy.example"}, "contains_url"),
    ({**GOOD_AREA, "specific_area": "Harbor Systems Monitoring"}, "names_organization"),
    ({**GOOD_AREA, "specific_area": "YOLO Vessel Tracking"}, "names_specific_technology"),
    ({**GOOD_AREA, "functional_area": "x" * 81}, "too_long"),
])
async def test_a_bad_area_is_retried_once_then_accepted(bad, reason):
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad, GOOD_AREA])

    output = await ClassifyAreaSkill(gateway).execute(area_input())

    assert output.area.specific_area == "Vessel Behavior Monitoring"
    assert reason in fake.calls[1].input_json            # the retry names the broken rule


async def test_two_bad_areas_raise():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [{**GOOD_AREA, "functional_area": "Navy"}] * 2)
    with pytest.raises(AreaRejectedError) as raised:
        await ClassifyAreaSkill(gateway).execute(area_input())
    assert raised.value.rejection_summary == {"same_as_branch": 2}


async def test_area_gateway_failure_propagates():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await ClassifyAreaSkill(gateway).execute(area_input())


def test_fake_area_passes_the_checks():
    from app.domains.fyp.skills.classify_area import LLMAreaDraft, check_area

    reply = fake_area({"industry": "Defense", "branch": "Navy", "problem": brief_for_model(BRIEF)})
    area, reason = check_area(LLMAreaDraft(**reply), area_input())
    assert reason is None and area.functional_area == "Operations Monitoring"


# ── design_fyp ────────────────────────────────────────────────────────────────

async def test_first_design_uses_structured_reasoning_and_reports_safe_progress():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_DESIGN])

    output, progress = await collect(DesignFYPSkill(gateway), design_input())

    assert output.design.title == GOOD_DESIGN["title"]
    assert (output.provider, output.prompt_version) == ("fake", DESIGN_PROMPT_VERSION)
    assert [p.phase for p in progress] == [DesignPhase.DESIGNING_FYP, DesignPhase.CHECKING_DESIGN]
    assert progress[0].label == "Designing a student-sized FYP"
    assert gateway.router.profile(STRUCTURED_REASONING) is not None


def test_first_design_input_has_the_area_and_no_redesign():
    shown = build_llm_input(design_input())
    assert shown["functional_area"] == "Maritime Surveillance"
    assert shown["specific_area"] == "Vessel Behavior Monitoring"
    assert "redesign" not in shown


def test_redesign_input_has_the_controlled_request_note_and_previous_design():
    shown = build_llm_input(redesign_input(FYPAdjustment.CHANGE_TARGET_USER, note="For port staff"))
    assert shown["redesign"]["requested_change"] == ADJUSTMENT_REQUESTS[FYPAdjustment.CHANGE_TARGET_USER]
    assert shown["redesign"]["student_note"] == "For port staff"
    assert shown["redesign"]["previous_design"]["title"] == GOOD_DESIGN["title"]


def test_every_adjustment_has_a_request_and_none_is_about_more_ai():
    assert set(ADJUSTMENT_REQUESTS) == set(FYPAdjustment)
    assert {a.value for a in FYPAdjustment} == {
        "make_simpler", "change_target_user", "change_system_focus", "reduce_complexity",
    }


def test_redesign_needs_both_adjustment_and_previous_design():
    with pytest.raises(ValidationError):
        design_input(adjustment=FYPAdjustment.MAKE_SIMPLER)
    with pytest.raises(ValidationError):
        design_input(note="x" * 201, adjustment=FYPAdjustment.MAKE_SIMPLER,
                     previous_design=FYPDesign(**GOOD_DESIGN))


@pytest.mark.parametrize("bad, reason", [
    ({**GOOD_DESIGN, "summary": "Details at www.navy.example"}, "contains_url"),
    ({**GOOD_DESIGN, "title": "Rebuild Harbor Systems alerts"}, "names_organization"),
    ({**GOOD_DESIGN, "system_input": "The Kaggle AIS dataset"}, "names_specific_technology"),
    ({**GOOD_DESIGN, "summary": "Train an LSTM in TensorFlow"}, "names_specific_technology"),
    ({**GOOD_DESIGN, "title": "x" * 121}, "too_long"),
])
async def test_a_bad_design_is_retried_once_then_accepted(bad, reason):
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad, GOOD_DESIGN])

    output = await DesignFYPSkill(gateway).execute(design_input())

    assert output.design.title == GOOD_DESIGN["title"]
    assert output.rejection_summary == {reason: 1}
    assert reason in fake.calls[1].input_json


async def test_an_unchanged_redesign_is_rejected():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_DESIGN, {**GOOD_DESIGN, "title": "A simpler alert tool"}])

    output, progress = await collect(DesignFYPSkill(gateway), redesign_input())

    assert output.design.title == "A simpler alert tool"
    assert output.rejection_summary == {"unchanged": 1}
    assert progress[0].label == "Redesigning your FYP"


async def test_two_bad_designs_raise():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [{**GOOD_DESIGN, "summary": "Use PyTorch"}] * 2)
    with pytest.raises(DesignRejectedError) as raised:
        await DesignFYPSkill(gateway).execute(design_input())
    assert raised.value.rejection_summary == {"names_specific_technology": 2}


async def test_design_gateway_failure_propagates():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await DesignFYPSkill(gateway).execute(design_input())


@pytest.mark.parametrize("adjustment", list(FYPAdjustment))
def test_fake_design_passes_the_checks_for_every_adjustment(adjustment):
    from app.domains.fyp.skills.design_fyp import LLMFYPDesignDraft, check_design

    first = fake_design(build_llm_input(design_input()))
    first_design, reason = check_design(LLMFYPDesignDraft(**first), design_input())
    assert reason is None

    again = redesign_input(adjustment)
    again = again.model_copy(update={"previous_design": first_design})
    second = fake_design(build_llm_input(again))
    _, reason = check_design(LLMFYPDesignDraft(**second), again)
    assert reason is None


# ── Registration ──────────────────────────────────────────────────────────────

async def test_both_skills_are_registered_and_answer_in_fake_mode():
    registry = SkillRegistry()
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    register_fyp_skills(registry, MockSearchProvider(), gateway)

    assert {"classify_area", "design_fyp"} <= set(registry.list_skills())
    area = await registry.get("classify_area").execute(area_input())
    design = await registry.get("design_fyp").execute(design_input(area=area.area))
    assert design.design.title.startswith(BRIEF.title)


def test_skills_without_a_gateway_are_not_registered():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())
    assert "classify_area" not in registry and "design_fyp" not in registry
