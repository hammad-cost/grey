"""
Tests for the design_architecture skill (Release 0.11, Step 2). Fake LLM only.
"""
import copy

import pytest

from app.core.brain.schemas import (
    ArchitecturePreference,
    ComponentKind,
    FYPDesign,
    Metric,
    SystemTestKind,
    TechnologyPlan,
)
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.design_architecture import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.design_architecture import (
    ArchitecturePhase,
    ArchitecturePlanRejectedError,
    DesignArchitectureInput,
    DesignArchitectureSkill,
    LLMTechnicalPlanDraft,
    build_llm_input,
    check_plan_draft,
)
from app.domains.fyp.skills.design_architecture.fake import fake_technical_plan
from app.domains.fyp.skills.plan_technology.fake import fake_technology_plan
from app.domains.fyp.skills.plan_technology.validation import check_plan_draft as check_technology
from app.domains.fyp.skills.plan_technology import LLMTechnologyPlanDraft, build_llm_input as technology_input
from tests.unit.test_brain_ai_strategy import ml_strategy, rule_based_strategy
from tests.unit.test_brain_datasets import public
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_fyp_design_skills import BRIEF, GOOD_DESIGN, WS, collect, gateway_and_fake
from tests.unit.test_plan_technology_skill import GOOD_PLAN as GOOD_TECHNOLOGY, MODELS, tech_input


def technology(strategy=None, simpler=False) -> TechnologyPlan:
    """A technology plan built the way the fake model builds it (so it passes the rules)."""
    input = tech_input(strategy=strategy)
    reply = fake_technology_plan({**technology_input(input), **({"replan": {}} if simpler else {})})
    return check_technology(LLMTechnologyPlanDraft(**reply), input)[0]


def arch_input(preference=None, previous=None, strategy=None, technology_plan=None) -> DesignArchitectureInput:
    strategy = strategy or ml_strategy()
    return DesignArchitectureInput(
        workspace_id=WS, industry="Defense", branch="Navy", problem=BRIEF, design=FYPDesign(**GOOD_DESIGN),
        definition=make_definition(), strategy=strategy, dataset=public(1), models=MODELS,
        technology=technology_plan or technology(strategy), preference=preference, previous_plan=previous,
    )


def component(n, kind, technology=""):
    return {"id": f"c{n}", "name": f"Part {n}", "kind": kind, "role": "Does a job", "technology": technology}


GOOD_PLAN = {
    "summary": "Tracks flow through a model to a dashboard.",
    "components": [
        component(1, "data_source", "Vessel tracks dataset 1"),
        component(2, "model", "Python with scikit-learn"),
        component(3, "backend", "FastAPI"),
        component(4, "interface", "React"),
        component(5, "user"),
    ],
    "flows": [{"source": f"c{n}", "target": f"c{n + 1}", "data": "results"} for n in range(1, 5)],
    "metrics": [{"metric": "recall", "why": "Missing an unusual track is costly.", "goal": "Recall of at least 0.8"}],
    "tests": [{"kind": "baseline_comparison", "how": "Compare with a threshold rule."}],
    "baseline": "A simple threshold rule",
}


def bad(change) -> dict:
    reply = copy.deepcopy(GOOD_PLAN)
    change(reply)
    return reply


def check(reply, input=None):
    return check_plan_draft(LLMTechnicalPlanDraft(**reply), input or arch_input())


def test_the_model_sees_the_approved_decisions():
    shown = build_llm_input(arch_input())
    assert shown["ai_strategy"]["uses_ai"] is True
    assert "recall" in shown["ai_strategy"]["allowed_metrics"] and "rmse" not in shown["ai_strategy"]["allowed_metrics"]
    assert {"area": "frontend", "choice": "React"} in shown["technology_stack"]
    assert shown["model_plan"] == [{"name": "track-model", "use": "fine_tune"}]
    assert shown["workflow_steps"] and shown["modules"]
    assert "redesign" not in shown and "Harbor Systems" not in str(shown)


def test_the_prompt_lists_every_kind_metric_and_test():
    for value in [*ComponentKind, *Metric, *SystemTestKind]:
        assert value.value in INSTRUCTIONS


def test_a_good_reply_becomes_a_plan():
    plan, reason = check(GOOD_PLAN)
    assert reason is None
    assert plan.architecture.components[4].technology is None
    assert plan.evaluation.metrics[0].metric == Metric.RECALL and plan.evaluation.baseline == "A simple threshold rule"


@pytest.mark.parametrize("change, reason", [
    (lambda r: r["components"][0].update(kind="cloud"), "unknown_choice"),
    (lambda r: r["metrics"][0].update(metric="happiness"), "unknown_choice"),
    (lambda r: r["tests"][0].update(kind="vibes"), "unknown_choice"),
    (lambda r: r["components"][0].update(role=" "), "empty"),
    (lambda r: r.update(components=r["components"][:3]), "wrong_count"),
    (lambda r: r.update(tests=[]), "wrong_count"),
    (lambda r: r["components"][1].update(technology="TensorFlow"), "unknown_technology"),
    (lambda r: r["flows"][0].update(data="x" * 500), "too_long"),
    (lambda r: r.update(summary="See https://example.com"), "contains_url"),
    (lambda r: r["flows"].pop(), "unconnected_component"),
    (lambda r: r["flows"][0].update(target="c9"), "unknown_component"),
    (lambda r: r["components"][3].update(kind="storage"), "missing_interface"),
    (lambda r: r.update(metrics=[]), "missing_ai_metrics"),
    (lambda r: r["metrics"][0].update(metric="rmse"), "metric_mismatch"),
    (lambda r: r.update(baseline=""), "missing_baseline"),
])
def test_bad_replies_are_rejected(change, reason):
    plan, rejected = check(bad(change))
    assert plan is None and rejected == reason


def test_a_project_without_ai_has_no_model_or_metrics():
    reply = bad(lambda r: r["components"][1].update(technology=""))    # the no-AI stack has no AI library
    _, reason = check(reply, arch_input(strategy=rule_based_strategy()))
    assert reason == "ai_without_ai"


async def test_the_skill_designs_checks_and_retries_once():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r.update(metrics=[])), GOOD_PLAN])
    output, progress = await collect(DesignArchitectureSkill(gateway), arch_input())
    assert output.rejection_summary == {"missing_ai_metrics": 1} and output.prompt_version == PROMPT_VERSION
    assert [p.phase for p in progress] == [ArchitecturePhase.DESIGNING, ArchitecturePhase.CHECKING] * 2

    fake.script("fake-model", [bad(lambda r: r.update(tests=[]))] * 2)
    with pytest.raises(ArchitecturePlanRejectedError):
        await DesignArchitectureSkill(gateway).execute(arch_input())
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await DesignArchitectureSkill(gateway).execute(arch_input())


async def test_a_redesign_shows_the_request_and_previous_plan():
    gateway, fake = gateway_and_fake()
    previous, _ = check(GOOD_PLAN)
    fake.script("fake-model", [GOOD_PLAN])
    _, progress = await collect(DesignArchitectureSkill(gateway), arch_input(ArchitecturePreference.SIMPLER, previous))
    assert progress[0].label == "Making the architecture simpler"
    assert "simpler" in fake.calls[-1].input_json and "previous_answer" in fake.calls[-1].input_json


def test_fake_answers_pass_the_checks():
    previous, _ = check(GOOD_PLAN)
    for strategy in (ml_strategy(), rule_based_strategy()):
        for simpler_stack in (False, True):
            for preference in (None, ArchitecturePreference.SIMPLER):
                input = arch_input(preference, previous, strategy, technology(strategy, simpler_stack))
                plan, reason = check_plan_draft(LLMTechnicalPlanDraft(**fake_technical_plan(build_llm_input(input))), input)
                assert reason is None, (strategy.necessity, simpler_stack, preference, reason)


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    output = await registry.get("design_architecture").execute(arch_input())
    assert ComponentKind.MODEL in [c.kind for c in output.plan.architecture.components]


def test_the_technology_fixture_matches_the_good_plan():
    assert GOOD_TECHNOLOGY["stack"][0]["choice"] == "React"
