"""
Tests for the plan_technology skill (Release 0.10, Step 2). Fake LLM only.
"""
import copy

import pytest

from app.core.brain.schemas import (
    FYPDesign,
    HardwareKind,
    ModelKind,
    ModelOption,
    ModelPlan,
    ModelUse,
    StackArea,
    TechnologyPreference,
)
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.plan_technology import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.plan_technology import (
    LLMTechnologyPlanDraft,
    PlanTechnologyInput,
    PlanTechnologySkill,
    TechnologyPhase,
    TechnologyPlanRejectedError,
    build_llm_input,
    check_plan_draft,
)
from app.domains.fyp.skills.plan_technology.fake import fake_technology_plan
from tests.unit.test_brain_ai_strategy import ml_strategy, rule_based_strategy
from tests.unit.test_brain_datasets import public
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_fyp_design_skills import AREA, BRIEF, GOOD_DESIGN, WS, collect, gateway_and_fake

MODELS = ModelPlan(needs_model=True, summary="Fine-tune one model.", options=[ModelOption(
    kind=ModelKind.PRETRAINED_MODEL, name="track-model", source="huggingface.co",
    url="https://huggingface.co/a/track-model", use=ModelUse.FINE_TUNE, reason="r", role="checker",
    limitations=["l"],
)])

GOOD_PLAN = {
    "summary": "A small web app with a trained model, on a laptop.",
    "stack": [
        {"area": "frontend", "choice": "React", "reason": "One interactive dashboard is the main need."},
        {"area": "backend", "choice": "FastAPI", "reason": "A small Python API serves the model."},
        {"area": "ai_ml", "choice": "PyTorch", "reason": "It supports fine-tuning the chosen model."},
    ],
    "hardware": [
        {"kind": "normal_laptop", "name": "A normal laptop", "purpose": "Build and demo", "essential": True,
         "cost": "none", "alternative": ""},
        {"kind": "cloud_gpu", "name": "Rented cloud GPU", "purpose": "Faster fine-tuning", "essential": False,
         "cost": "high", "alternative": "Free Google Colab"},
    ],
}


def tech_input(preference=None, previous=None, strategy=None) -> PlanTechnologyInput:
    return PlanTechnologyInput(
        workspace_id=WS, industry="Defense", branch="Navy", area=AREA, problem=BRIEF,
        design=FYPDesign(**GOOD_DESIGN), definition=make_definition(), strategy=strategy or ml_strategy(),
        dataset=public(1), models=MODELS, preference=preference, previous_plan=previous,
    )


def bad(change) -> dict:
    reply = copy.deepcopy(GOOD_PLAN)
    change(reply)
    return reply


def check(reply, input=None):
    return check_plan_draft(LLMTechnologyPlanDraft(**reply), input or tech_input())


def test_the_model_sees_the_approved_decisions():
    shown = build_llm_input(tech_input())
    assert shown["ai_strategy"]["uses_ai"] is True
    assert shown["model_plan"]["options"] == [{"name": "track-model", "kind": "pretrained_model", "use": "fine_tune"}]
    assert shown["selected_dataset"]["name"] == "Vessel tracks dataset 1"
    assert shown["core_features"] == ["Core 0", "Core 1", "Core 2"] and shown["modules"]
    assert "replan" not in shown and "Harbor Systems" not in str(shown)


def test_the_prompt_asks_for_decisions_and_lists_every_value():
    assert "DECISIONS, not lists of options" in INSTRUCTIONS
    for value in [*StackArea, *HardwareKind]:
        assert value.value in INSTRUCTIONS


def test_a_good_reply_becomes_a_plan():
    plan, reason = check(GOOD_PLAN)
    assert reason is None
    assert [c.area for c in plan.stack] == [StackArea.FRONTEND, StackArea.BACKEND, StackArea.AI_ML]
    assert plan.hardware[0].alternative is None and plan.hardware[1].alternative == "Free Google Colab"


@pytest.mark.parametrize("change, reason", [
    (lambda r: r["stack"][0].update(area="mobile_app"), "unknown_choice"),
    (lambda r: r["hardware"][0].update(cost="cheap"), "unknown_choice"),
    (lambda r: r["hardware"][0].update(kind="supercomputer"), "unknown_choice"),
    (lambda r: r["stack"][0].update(choice="React or Vue"), "option_list"),
    (lambda r: r["stack"][0].update(choice="React, Vue, Angular"), "option_list"),
    (lambda r: r["stack"][0].update(reason=" "), "empty"),
    (lambda r: r.update(stack=r["stack"][:1]), "wrong_count"),
    (lambda r: r.update(hardware=[]), "wrong_count"),
    (lambda r: r["stack"][0].update(reason="x" * 500), "too_long"),
    (lambda r: r["stack"][0].update(reason="Docs at https://react.dev"), "contains_url"),
    (lambda r: r["stack"][1].update(area="frontend"), "duplicate_area"),
    (lambda r: r["stack"].pop(2), "missing_ai_ml"),
    (lambda r: r["hardware"][1].update(alternative=""), "missing_alternative"),
])
def test_bad_replies_are_rejected(change, reason):
    plan, rejected = check(bad(change))
    assert plan is None and rejected == reason


def test_a_project_without_ai_must_not_get_ai_tools():
    _, reason = check(GOOD_PLAN, tech_input(strategy=rule_based_strategy()))
    assert reason == "ai_without_ai"


async def test_the_skill_plans_checks_and_retries_once():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r["stack"][0].update(choice="React or Vue")), GOOD_PLAN])
    output, progress = await collect(PlanTechnologySkill(gateway), tech_input())
    assert output.rejection_summary == {"option_list": 1}
    assert output.prompt_version == PROMPT_VERSION
    assert [p.phase for p in progress] == [TechnologyPhase.PLANNING, TechnologyPhase.CHECKING] * 2

    fake.script("fake-model", [bad(lambda r: r.update(hardware=[]))] * 2)
    with pytest.raises(TechnologyPlanRejectedError):
        await PlanTechnologySkill(gateway).execute(tech_input())
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await PlanTechnologySkill(gateway).execute(tech_input())


async def test_a_replan_shows_the_request_and_the_previous_plan():
    gateway, fake = gateway_and_fake()
    previous, _ = check(GOOD_PLAN)
    fake.script("fake-model", [GOOD_PLAN])
    output, progress = await collect(PlanTechnologySkill(gateway), tech_input(TechnologyPreference.SIMPLER, previous))
    assert progress[0].label == "Making the plan simpler and cheaper"
    assert "simpler" in fake.calls[-1].input_json and "previous_answer" in fake.calls[-1].input_json


def test_fake_answers_pass_the_checks():
    for strategy in (ml_strategy(), rule_based_strategy()):
        for preference in (None, TechnologyPreference.SIMPLER):
            input = tech_input(preference, check(GOOD_PLAN)[0], strategy)
            plan, reason = check_plan_draft(LLMTechnologyPlanDraft(**fake_technology_plan(build_llm_input(input))), input)
            assert reason is None, (strategy.necessity, preference, reason)


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    output = await registry.get("plan_technology").execute(tech_input())
    assert StackArea.AI_ML in [c.area for c in output.plan.stack]
