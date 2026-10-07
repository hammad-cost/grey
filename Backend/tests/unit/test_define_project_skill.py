"""
Tests for the define_project skill (Release 0.6, Step 2).

Covers what the skill sends the model, how bad replies are rejected (wrong
list sizes, links, organization names, named technologies, duplicate
features…), the one retry, the fake-mode answer, and registration.

The model is always FakeLLMProvider (scripted per test). No network, no keys.
"""
import copy

import pytest

from app.core.brain.schemas import FYPDesign, ScopeKind
from app.core.config.settings import Settings
from app.core.llm import STRUCTURED_REASONING, LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.prompts.define_project import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.define_project import (
    DefineProjectInput,
    DefineProjectSkill,
    DefinitionPhase,
    DefinitionRejectedError,
    LLMProjectDefinitionDraft,
    build_llm_input,
    check_definition,
)
from app.domains.fyp.skills.define_project.fake import fake_definition
from tests.unit.test_fyp_design_skills import AREA, BRIEF, GOOD_DESIGN, WS, collect, gateway_and_fake


def feature(title: str) -> dict:
    return {"title": title, "description": f"{title} for the analyst."}


GOOD_DEFINITION = {
    "problem_definition": {
        "problem_statement": "Analysts miss unusual vessel movements in large volumes of data.",
        "affected_users": "Coastal monitoring analysts",
        "why_it_matters": "Missed movements delay responses.",
        "current_solutions": "Large monitoring platforms exist but are complex.",
        "gap": "No simple tool explains each alert.",
        "what_will_be_built": "A web tool that flags unusual tracks and explains them.",
    },
    "system_purpose": "Help analysts spot and understand unusual vessel movements.",
    "modules": [
        {"name": "Data upload", "purpose": "Load position reports."},
        {"name": "Alert view", "purpose": "Show unusual tracks with reasons."},
    ],
    "workflow_steps": ["Upload reports", "The tool checks each track", "The analyst reviews alerts"],
    "core_features": [feature("Report upload"), feature("Track checking"), feature("Alert list")],
    "optional_features": [feature("Report export")],
    "out_of_scope": [feature("Live feeds"), feature("Mobile app")],
}


def definition_input() -> DefineProjectInput:
    return DefineProjectInput(
        workspace_id=WS, industry="Defense", branch="Navy", area=AREA, problem=BRIEF, design=FYPDesign(**GOOD_DESIGN),
    )


def bad(change) -> dict:
    reply = copy.deepcopy(GOOD_DEFINITION)
    change(reply)
    return reply


# ── What the model sees ───────────────────────────────────────────────────────

def test_the_model_sees_the_problem_area_and_approved_design_only():
    shown = build_llm_input(definition_input())
    assert shown["approved_design"]["title"] == GOOD_DESIGN["title"]
    assert shown["specific_area"] == "Vessel Behavior Monitoring"
    text = str(shown)
    assert "Harbor Systems" not in text            # organizations are never shown
    assert "https://" not in text and "ev-1" not in text


def test_the_prompt_leaves_ai_and_technology_to_later_stages():
    assert "Do NOT decide whether" in INSTRUCTIONS
    assert "Do NOT choose or name a specific dataset" in INSTRUCTIONS


# ── Good replies ──────────────────────────────────────────────────────────────

async def test_definition_uses_structured_reasoning_and_reports_safe_progress():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_DEFINITION])

    output, progress = await collect(DefineProjectSkill(gateway), definition_input())

    definition = output.definition
    assert definition.problem_definition.gap == "No simple tool explains each alert."
    assert [m.name for m in definition.proposed_solution.modules] == ["Data upload", "Alert view"]
    assert [(i.title, i.kind) for i in definition.scope] == [
        ("Report upload", ScopeKind.CORE), ("Track checking", ScopeKind.CORE), ("Alert list", ScopeKind.CORE),
        ("Report export", ScopeKind.OPTIONAL),
        ("Live feeds", ScopeKind.OUT_OF_SCOPE), ("Mobile app", ScopeKind.OUT_OF_SCOPE),
    ]
    assert (output.provider, output.prompt_version) == ("fake", PROMPT_VERSION)
    assert [p.phase for p in progress] == [DefinitionPhase.DEFINING_PROJECT, DefinitionPhase.CHECKING_DEFINITION]
    assert fake.calls[0].schema_name == "LLMProjectDefinitionDraft"
    assert gateway.router.profile(STRUCTURED_REASONING) is not None


def test_extra_spaces_are_tidied():
    reply = bad(lambda r: r["core_features"][0].update(title="  Report   upload "))
    definition, reason = check_definition(LLMProjectDefinitionDraft(**reply), definition_input())
    assert reason is None
    assert definition.scope[0].title == "Report upload"


# ── Bad replies ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("change, reason", [
    (lambda r: r.update(core_features=r["core_features"][:2]), "wrong_count"),
    (lambda r: r.update(optional_features=[]), "wrong_count"),
    (lambda r: r.update(out_of_scope=r["out_of_scope"][:1]), "wrong_count"),
    (lambda r: r.update(modules=r["modules"][:1]), "wrong_count"),
    (lambda r: r.update(workflow_steps=r["workflow_steps"] * 3), "wrong_count"),
    (lambda r: r["problem_definition"].update(gap="   "), "empty"),
    (lambda r: r.update(system_purpose="See https://vessels.example for details."), "contains_url"),
    (lambda r: r["core_features"][0].update(title="x" * 81), "too_long"),
    (lambda r: r["out_of_scope"][0].update(title="report UPLOAD"), "duplicate_feature"),
    (lambda r: r["problem_definition"].update(current_solutions="Harbor Systems sells a platform."),
     "names_organization"),
    (lambda r: r["modules"][1].update(purpose="A dashboard built with Django."), "names_specific_technology"),
])
def test_bad_replies_are_rejected(change, reason):
    _, found = check_definition(LLMProjectDefinitionDraft(**bad(change)), definition_input())
    assert found == reason


async def test_a_bad_reply_is_retried_once_with_feedback():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r.update(optional_features=[])), GOOD_DEFINITION])

    output = await DefineProjectSkill(gateway).execute(definition_input())

    assert output.rejection_summary == {"wrong_count": 1}
    assert len(fake.calls) == 2
    assert "wrong_count" in fake.calls[1].input_json
    assert "Report upload" not in fake.calls[1].input_json      # the bad reply is never echoed back


async def test_two_bad_replies_raise():
    gateway, fake = gateway_and_fake()
    broken = bad(lambda r: r.update(system_purpose="Uses PyTorch."))
    fake.script("fake-model", [broken, broken])

    with pytest.raises(DefinitionRejectedError) as error:
        await DefineProjectSkill(gateway).execute(definition_input())
    assert error.value.rejection_summary == {"names_specific_technology": 2}


async def test_gateway_failure_propagates():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await DefineProjectSkill(gateway).execute(definition_input())


# ── Fake mode and registration ────────────────────────────────────────────────

def test_fake_definition_passes_the_checks():
    reply = fake_definition(build_llm_input(definition_input()))
    definition, reason = check_definition(LLMProjectDefinitionDraft(**reply), definition_input())
    assert reason is None
    assert definition.problem_definition.affected_users == GOOD_DESIGN["target_user"]


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))

    output = await registry.get("define_project").execute(definition_input())
    assert sum(1 for item in output.definition.scope if item.kind == ScopeKind.CORE) == 3


def test_skill_without_a_gateway_is_not_registered():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())
    assert "define_project" not in registry
