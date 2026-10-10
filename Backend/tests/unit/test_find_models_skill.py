"""
Tests for the find_models skill (Release 0.9, Step 3).

Covers the code-built answer for a project without AI, what the model sees,
how bad replies are rejected, the retry, failed searches, re-searches, the
fake-mode answers, and registration. Fake LLM and scripted / mock search only.
"""
import copy

import pytest

from app.core.brain.schemas import ModelKind, ModelPreference, ModelUse
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import SearchResult, SearchUnavailable
from app.domains.fyp.prompts.find_models import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.find_datasets.search import search_datasets
from app.domains.fyp.skills.find_models import (
    FindModelsInput,
    FindModelsSkill,
    LLMModelPlanDraft,
    ModelPhase,
    ModelPlanRejectedError,
    ModelsUnavailableError,
    build_llm_input,
    check_plan_draft,
)
from app.domains.fyp.skills.find_models.fake import fake_model_plan
from app.domains.fyp.skills.find_models.search import build_model_queries, is_model_page
from tests.unit.test_brain_ai_strategy import ml_strategy, rule_based_strategy
from tests.unit.test_brain_datasets import public
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_dataset_search import ScriptedSearch
from tests.unit.test_fyp_design_skills import AREA, BRIEF, WS, collect, gateway_and_fake

PAGES = [
    SearchResult(title="vessel-track-anomaly", url="https://huggingface.co/someone/vessel-track-anomaly",
                 snippet="Anomaly detector for ship tracks, 91% recall on the test set.", provider="scripted"),
    SearchResult(title="ais-anomaly (GitHub)", url="https://github.com/someone/ais-anomaly",
                 snippet="Open-source code for finding unusual AIS tracks.", provider="scripted"),
]


def option(**changes) -> dict:
    values = {
        "candidate_number": 1, "kind": "pretrained_model", "name": "vessel-track-anomaly", "use": "fine_tune",
        "reason": "A close match; fine-tune it on your dataset.", "role": "The track checker",
        "limitations": ["Trained on another region"],
    }
    values.update(changes)
    return values


GOOD_PLAN = {
    "summary": "Fine-tune the first model and compare against the code.",
    "options": [option(), option(candidate_number=2, kind="code_repository", name="ais-anomaly", use="benchmark")],
}


def model_input(preference=None, previous=None, strategy=None, known=None) -> FindModelsInput:
    return FindModelsInput(
        workspace_id=WS, industry="Defense", branch="Navy", area=AREA, problem=BRIEF,
        definition=make_definition(), strategy=strategy or ml_strategy(), dataset=public(1),
        preference=preference, previous_plan=previous, known_candidates=known or [],
    )


async def candidates():
    query = build_model_queries("Defense", "Navy", "Vessels", "anomaly_detection")[0]
    return (await search_datasets(ScriptedSearch(PAGES), [query], max_searches=1, is_wanted=is_model_page)).candidates


def bad(change) -> dict:
    reply = copy.deepcopy(GOOD_PLAN)
    change(reply)
    return reply


async def check(reply, input=None):
    return check_plan_draft(LLMModelPlanDraft(**reply), input or model_input(), await candidates())


# ── What the model sees ───────────────────────────────────────────────────────

async def test_the_model_sees_the_strategy_dataset_and_numbered_pages():
    shown = build_llm_input(model_input(), await candidates())
    assert shown["ai_strategy"]["task_type"] == "anomaly_detection"
    assert shown["selected_dataset"] == {"name": "Vessel tracks dataset 1", "kind": "public"}
    assert [c["number"] for c in shown["candidates"]] == [1, 2]
    assert "https://" not in str(shown) and "Harbor Systems" not in str(shown)


def test_the_prompt_lists_every_kind_and_use():
    for value in [*ModelKind, *ModelUse]:
        assert value.value in INSTRUCTIONS


# ── Checks ────────────────────────────────────────────────────────────────────

async def test_a_good_reply_becomes_a_plan_with_found_links():
    plan, reason = await check(GOOD_PLAN)
    assert reason is None and plan.needs_model
    assert plan.options[0].url == PAGES[0].url and plan.options[0].use == ModelUse.FINE_TUNE
    assert plan.options[1].source == "github.com"


async def test_an_empty_list_is_a_valid_answer():
    plan, reason = await check({"summary": "Nothing fits; train your own model.", "options": []})
    assert reason is None and plan.options == []


async def test_a_percentage_the_page_states_is_allowed():
    plan, reason = await check(bad(lambda r: r["options"][0].update(reason="Reports 91% recall on its test set.")))
    assert reason is None


@pytest.mark.parametrize("change, reason", [
    (lambda r: r["options"][0].update(kind="dataset"), "unknown_choice"),
    (lambda r: r["options"][0].update(use="replace_everything"), "unknown_choice"),
    (lambda r: r["options"][0].update(candidate_number=7), "unknown_candidate"),
    (lambda r: r["options"][0].update(name=" "), "empty"),
    (lambda r: r.update(summary=""), "empty"),
    (lambda r: r["options"][0].update(limitations=[]), "wrong_count"),
    (lambda r: r.update(options=[option()] * 4), "wrong_count"),
    (lambda r: r["options"][0].update(reason="It reaches 99% accuracy."), "unsupported_fact"),
    (lambda r: r["options"][0].update(reason="See github.com for it."), "contains_url"),
    (lambda r: r["options"][0].update(role="x" * 600), "too_long"),
    (lambda r: r["options"][1].update(candidate_number=1), "same_model"),
])
async def test_bad_replies_are_rejected(change, reason):
    plan, rejected = await check(bad(change))
    assert plan is None and rejected == reason


# ── Running the skill ─────────────────────────────────────────────────────────

async def test_a_project_without_ai_needs_no_search_and_no_model():
    gateway, fake = gateway_and_fake()
    search = ScriptedSearch(PAGES)
    output, progress = await collect(FindModelsSkill(search, gateway), model_input(strategy=rule_based_strategy()))
    assert output.plan.needs_model is False and output.plan.options == []
    assert "doesn't use AI" in output.plan.summary
    assert search.queries == [] and fake.calls == []
    assert (output.provider, output.prompt_version) == ("grey", "none")
    assert [p.phase for p in progress] == [ModelPhase.SEARCHING]


async def test_the_skill_searches_chooses_and_checks():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_PLAN])
    search = ScriptedSearch(PAGES)
    output, progress = await collect(FindModelsSkill(search, gateway), model_input())
    assert len(output.plan.options) == 2 and output.searches_used == 4
    assert output.prompt_version == PROMPT_VERSION
    assert [p.phase for p in progress] == [ModelPhase.SEARCHING, ModelPhase.CHOOSING, ModelPhase.CHECKING]


async def test_a_bad_reply_is_retried_once_then_given_up():
    gateway, fake = gateway_and_fake()
    broken = bad(lambda r: r["options"][0].update(candidate_number=9))
    fake.script("fake-model", [broken, GOOD_PLAN])
    output = await FindModelsSkill(ScriptedSearch(PAGES), gateway).execute(model_input())
    assert output.rejection_summary == {"unknown_candidate": 1}

    fake.script("fake-model", [broken, broken])
    with pytest.raises(ModelPlanRejectedError) as raised:
        await FindModelsSkill(ScriptedSearch(PAGES), gateway).execute(model_input())
    assert raised.value.searches_used == 4


async def test_failures_are_passed_on():
    gateway, fake = gateway_and_fake()
    with pytest.raises(ModelsUnavailableError):
        await FindModelsSkill(ScriptedSearch(error=SearchUnavailable("down")), gateway).execute(model_input())
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await FindModelsSkill(ScriptedSearch(PAGES), gateway).execute(model_input())


async def test_other_models_skips_the_pages_shown_before():
    gateway, fake = gateway_and_fake()
    previous, _ = await check(GOOD_PLAN)
    fake.script("fake-model", [{"summary": "Nothing new fits.", "options": []}])
    search = ScriptedSearch(PAGES)
    output = await FindModelsSkill(search, gateway).execute(
        model_input(ModelPreference.OTHER_OPTIONS, previous, known=await candidates())
    )
    assert output.candidates == [] and len(search.queries) == 3
    assert "previous_answer" in fake.calls[-1].input_json


# ── Fake mode ─────────────────────────────────────────────────────────────────

async def test_fake_answers_pass_the_checks():
    found = await candidates()
    for cands in (found, found[:1], []):
        plan, reason = check_plan_draft(
            LLMModelPlanDraft(**fake_model_plan(build_llm_input(model_input(), cands))), model_input(), cands
        )
        assert reason is None, reason
        assert len(plan.options) == len(cands)


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    output = await registry.get("find_models").execute(model_input())
    assert output.searches_used == 4 and len(output.plan.options) == 2
