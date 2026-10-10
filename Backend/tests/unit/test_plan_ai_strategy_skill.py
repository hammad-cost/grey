"""
Tests for the plan_ai_strategy skill (Release 0.7, Step 2).

Covers what the skill sends the model (including a re-check), how bad replies
are rejected (unknown choices, inconsistent AI details, links, organization
names, named technologies…), the one retry, the fake-mode answers, and registration.

The model is always FakeLLMProvider (scripted per test). No network, no keys.
"""
import copy

import pytest

from app.core.brain.schemas import (
    AIApproach,
    AINecessity,
    AIStrategy,
    AIStrategyPreference,
    AITaskType,
    FYPDesign,
)
from app.core.config.settings import Settings
from app.core.llm import STRUCTURED_REASONING, LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.plan_ai_strategy import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.plan_ai_strategy import (
    AIStrategyPhase,
    AIStrategyRejectedError,
    LLMAIStrategyDraft,
    PlanAIStrategyInput,
    PlanAIStrategySkill,
    build_llm_input,
    check_strategy_draft,
)
from app.domains.fyp.skills.plan_ai_strategy.fake import fake_strategy
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_fyp_design_skills import AREA, BRIEF, GOOD_DESIGN, WS, collect, gateway_and_fake

GOOD_STRATEGY = {
    "necessity": "traditional_ml",
    "necessity_reason": "Unusual tracks are hard to describe with fixed rules.",
    "without_ai": "Speed and route limits could flag some tracks, but would miss new patterns.",
    "ai_component": "The track checker that scores how unusual each track is.",
    "non_ai_components": ["Report upload", "Alert list"],
    "task_type": "anomaly_detection",
    "primary_strategy": {"approach": "train_model", "reason": "Public track data is enough to train on."},
    "fallback_strategy": {"approach": "hybrid", "reason": "Rules plus a small model if training is weak."},
}

NO_AI_STRATEGY = {
    "necessity": "rule_based",
    "necessity_reason": "Clear limits describe the unusual tracks well.",
    "without_ai": "Speed and route rules flag the tracks.",
    "ai_component": "",
    "non_ai_components": ["Report upload", "Rule checker", "Alert list"],
    "task_type": "none",
    "primary_strategy": {"approach": "none", "reason": ""},
    "fallback_strategy": {"approach": "none", "reason": ""},
}


def strategy_input(preference=None, previous=None) -> PlanAIStrategyInput:
    return PlanAIStrategyInput(
        workspace_id=WS, industry="Defense", branch="Navy", area=AREA, problem=BRIEF,
        design=FYPDesign(**GOOD_DESIGN), definition=make_definition(),
        preference=preference, previous_strategy=previous,
    )


def bad(change, base=GOOD_STRATEGY) -> dict:
    reply = copy.deepcopy(base)
    change(reply)
    return reply


def check(reply: dict, input: PlanAIStrategyInput | None = None):
    return check_strategy_draft(LLMAIStrategyDraft(**reply), input or strategy_input())


# ── What the model sees ───────────────────────────────────────────────────────

def test_the_model_sees_the_approved_definition_and_scope():
    shown = build_llm_input(strategy_input())
    definition = shown["project_definition"]
    assert [f["title"] for f in definition["core_features"]] == ["Core 0", "Core 1", "Core 2"]
    assert definition["out_of_scope"] == ["Out 0", "Out 1"]
    assert shown["approved_design"]["title"] == GOOD_DESIGN["title"]
    assert "recheck" not in shown
    text = str(shown)
    assert "Harbor Systems" not in text                    # organizations are never shown
    assert "https://" not in text


def test_a_recheck_shows_the_request_and_the_previous_answer():
    previous, _ = check(GOOD_STRATEGY)
    shown = build_llm_input(strategy_input(AIStrategyPreference.WITHOUT_AI, previous))
    assert "without AI" in shown["recheck"]["student_request"]
    assert shown["recheck"]["previous_answer"]["necessity"] == "traditional_ml"


def test_the_prompt_never_forces_ai_and_leaves_technology_to_later_stages():
    assert "Never force AI" in INSTRUCTIONS
    assert "Do NOT name a specific dataset" in INSTRUCTIONS
    for value in [*AINecessity, *AITaskType, *AIApproach]:
        assert value.value in INSTRUCTIONS                  # every choice is listed for the model


# ── Good replies ──────────────────────────────────────────────────────────────

async def test_a_strategy_uses_structured_reasoning_and_reports_safe_progress():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_STRATEGY])

    output, progress = await collect(PlanAIStrategySkill(gateway), strategy_input())

    strategy = output.strategy
    assert strategy.necessity == AINecessity.TRADITIONAL_ML
    assert strategy.task_type == AITaskType.ANOMALY_DETECTION
    assert strategy.primary_strategy.approach == AIApproach.TRAIN_MODEL
    assert strategy.fallback_strategy.approach == AIApproach.HYBRID
    assert (output.provider, output.prompt_version) == ("fake", PROMPT_VERSION)
    assert [p.phase for p in progress] == [AIStrategyPhase.CHECKING_AI_NEED, AIStrategyPhase.CHECKING_ANSWER]
    assert fake.calls[0].schema_name == "LLMAIStrategyDraft"
    assert gateway.router.profile(STRUCTURED_REASONING) is not None


def test_a_project_without_ai_is_a_valid_answer():
    strategy, reason = check(NO_AI_STRATEGY)
    assert reason is None
    assert strategy.necessity == AINecessity.RULE_BASED
    assert strategy.ai_component is None and strategy.task_type is None
    assert strategy.primary_strategy is None and strategy.fallback_strategy is None


def test_choices_are_read_loosely_and_texts_tidied():
    reply = bad(lambda r: r.update(necessity=" Traditional_ML ", without_ai="  Rules   only. "))
    reply["fallback_strategy"] = {"approach": "None", "reason": ""}
    strategy, reason = check(reply)
    assert reason is None
    assert strategy.without_ai == "Rules only."
    assert strategy.fallback_strategy is None


# ── Bad replies ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("change, reason", [
    (lambda r: r.update(necessity="deep_learning"), "unknown_choice"),
    (lambda r: r.update(necessity="none"), "unknown_choice"),
    (lambda r: r.update(task_type="robotics"), "unknown_choice"),
    (lambda r: r["primary_strategy"].update(approach="buy_it"), "unknown_choice"),
    (lambda r: r.update(necessity_reason="  "), "empty"),
    (lambda r: r["primary_strategy"].update(reason=""), "empty"),
    (lambda r: r.update(non_ai_components=[]), "wrong_count"),
    (lambda r: r.update(non_ai_components=["a", "b", "c", "d", "e", "f", "g"]), "wrong_count"),
    (lambda r: r.update(task_type="none"), "missing_ai_details"),
    (lambda r: r.update(ai_component=""), "missing_ai_details"),
    (lambda r: r["primary_strategy"].update(approach="use_api"), "approach_mismatch"),
    (lambda r: r.update(task_type="generative_ai"), "approach_mismatch"),
    (lambda r: r["fallback_strategy"].update(approach="train_model"), "same_fallback"),
    (lambda r: r.update(without_ai="See https://vessels.example for rules."), "contains_url"),
    (lambda r: r.update(necessity_reason="x" * 501), "too_long"),
    (lambda r: r.update(non_ai_components=["x" * 121]), "too_long"),
    (lambda r: r.update(without_ai="Harbor Systems already uses rules."), "names_organization"),
    (lambda r: r["primary_strategy"].update(reason="Train it with PyTorch."), "names_specific_technology"),
])
def test_bad_replies_are_rejected(change, reason):
    _, found = check(bad(change))
    assert found == reason


def test_ai_details_on_a_no_ai_verdict_are_rejected():
    _, found = check(bad(lambda r: r.update(task_type="classification"), NO_AI_STRATEGY))
    assert found == "ai_details_without_ai"


async def test_a_bad_reply_is_retried_once_with_feedback():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r.update(task_type="none")), GOOD_STRATEGY])

    output = await PlanAIStrategySkill(gateway).execute(strategy_input())

    assert output.rejection_summary == {"missing_ai_details": 1}
    assert len(fake.calls) == 2
    assert "missing_ai_details" in fake.calls[1].input_json
    assert "track checker" not in fake.calls[1].input_json     # the bad reply is never echoed back


async def test_two_bad_replies_raise():
    gateway, fake = gateway_and_fake()
    broken = bad(lambda r: r.update(necessity="magic"))
    fake.script("fake-model", [broken, broken])

    with pytest.raises(AIStrategyRejectedError) as error:
        await PlanAIStrategySkill(gateway).execute(strategy_input())
    assert error.value.rejection_summary == {"unknown_choice": 2}


async def test_gateway_failure_propagates():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await PlanAIStrategySkill(gateway).execute(strategy_input())


# ── Fake mode and registration ────────────────────────────────────────────────

@pytest.mark.parametrize("problem_task", [
    "anomaly_detection", "classification", "forecasting", "recommendation", "nlp",
    "computer_vision", "decision_support", "optimization", "other",
])
def test_every_fake_answer_passes_the_checks(problem_task):
    llm_input = build_llm_input(strategy_input())
    llm_input["problem"]["task_type"] = problem_task
    _, reason = check(fake_strategy(llm_input))
    assert reason is None


@pytest.mark.parametrize("preference, necessity", [
    (AIStrategyPreference.WITHOUT_AI, AINecessity.RULE_BASED),
    (AIStrategyPreference.EXISTING_MODEL, AINecessity.EXISTING_MODEL),
])
def test_fake_rechecks_follow_the_preference(preference, necessity):
    previous, _ = check(GOOD_STRATEGY)
    input = strategy_input(preference, previous)
    strategy, reason = check(fake_strategy(build_llm_input(input)), input)
    assert reason is None
    assert strategy.necessity == necessity


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))

    output = await registry.get("plan_ai_strategy").execute(strategy_input())
    assert isinstance(output.strategy, AIStrategy)
    assert output.strategy.necessity == AINecessity.TRADITIONAL_ML          # the brief is anomaly detection
    assert output.strategy.non_ai_components == ["Core 0", "Core 1", "Core 2"]


def test_skill_without_a_gateway_is_not_registered():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())
    assert "plan_ai_strategy" not in registry
