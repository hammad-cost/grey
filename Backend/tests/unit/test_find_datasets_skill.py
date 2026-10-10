"""
Tests for the find_datasets skill (Release 0.8, Step 3).

Covers what the skill searches and sends the model (including re-searches),
how bad replies are rejected (a page that wasn't found, invented sizes and
licenses, own data without a plan, the same dataset twice, links…), the one
retry, failed searches, the fake-mode answers, and registration.

The model is always FakeLLMProvider (scripted per test); searches are scripted
or the mock provider. No network, no keys.
"""
import copy

import pytest

from app.core.brain.schemas import (
    NOT_STATED,
    AINecessity,
    AIStrategy,
    DatasetKind,
    DatasetPreference,
)
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.core.tools.search import SearchResult, SearchUnavailable
from app.domains.fyp.prompts.find_datasets import INSTRUCTIONS, PROMPT_VERSION
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.skills.find_datasets import (
    DatasetPhase,
    DatasetPlanRejectedError,
    DatasetsUnavailableError,
    FindDatasetsInput,
    FindDatasetsSkill,
    LLMDatasetPlanDraft,
    build_llm_input,
    check_plan_draft,
)
from app.domains.fyp.skills.find_datasets.fake import fake_dataset_plan
from app.domains.fyp.skills.find_datasets.search import search_datasets
from tests.unit.test_brain_ai_strategy import ml_strategy, rule_based_strategy
from tests.unit.test_brain_project_definition import make_definition
from tests.unit.test_dataset_search import ScriptedSearch
from tests.unit.test_fyp_design_skills import AREA, BRIEF, WS, collect, gateway_and_fake

PAGES = [
    SearchResult(
        title="Vessel AIS tracks with labelled anomalies",
        url="https://www.kaggle.com/datasets/someone/vessel-ais-anomalies",
        snippet="12,000 labelled vessel tracks from coastal waters. License: CC BY 4.0.",
        publisher="Kaggle",
        provider="scripted",
    ),
    SearchResult(
        title="Port traffic records",
        url="https://zenodo.org/records/7654321",
        snippet="Daily port traffic counts for several harbours.",
        provider="scripted",
    ),
]


def option(**changes) -> dict:
    values = {
        "kind": "public",
        "candidate_number": 1,
        "name": "Vessel AIS tracks with labelled anomalies",
        "size": "12,000 labelled vessel tracks",
        "main_features": ["Position", "Speed", "Heading"],
        "labels": "Each track is marked normal or unusual",
        "license": "CC BY 4.0",
        "relevance": "It holds the vessel tracks the anomaly checker must score.",
        "preprocessing": ["Remove duplicate positions", "Split by vessel"],
        "limitations": ["Coastal waters only"],
        "fit": "good",
        "how_to_get": "",
    }
    values.update(changes)
    return values


OWN = option(
    kind="synthetic", candidate_number=0, name="Simulated vessel tracks", size="A few thousand tracks",
    labels="You mark the unusual tracks", license="Your own data", fit="partial",
    how_to_get="Write a small simulator that adds unusual detours to normal routes.",
)

GOOD_PLAN = {
    "purpose": "Train and test the track checker.",
    "primary": option(),
    "alternative": option(candidate_number=2, name="Port traffic records", size=NOT_STATED,
                          license=NOT_STATED, fit="partial"),
}


def dataset_input(preference=None, previous=None, strategy: AIStrategy | None = None, known=None) -> FindDatasetsInput:
    return FindDatasetsInput(
        workspace_id=WS, industry="Defense", branch="Navy", area=AREA, problem=BRIEF,
        definition=make_definition(), strategy=strategy or ml_strategy(),
        preference=preference, previous_plan=previous, known_candidates=known or [],
    )


async def candidates():
    found = await search_datasets(ScriptedSearch(PAGES), [_q()], max_searches=1)
    return found.candidates


def _q():
    from app.domains.fyp.skills.find_datasets.search import build_dataset_queries
    return build_dataset_queries("Defense", "Navy", "Vessels", "anomaly_detection")[0]


def bad(change, base=GOOD_PLAN) -> dict:
    reply = copy.deepcopy(base)
    change(reply)
    return reply


async def check(reply: dict, input: FindDatasetsInput | None = None):
    return check_plan_draft(LLMDatasetPlanDraft(**reply), input or dataset_input(), await candidates())


# ── What the model sees ───────────────────────────────────────────────────────

async def test_the_model_sees_numbered_pages_without_links():
    shown = build_llm_input(dataset_input(), await candidates())
    assert [c["number"] for c in shown["candidates"]] == [1, 2]
    assert shown["candidates"][0]["site"] == "Kaggle"
    assert shown["candidates"][1]["site"] == "zenodo.org"
    assert shown["ai_strategy"] == {
        "uses_ai": True, "necessity": "traditional_ml",
        "ai_component": "The track checker that scores how unusual each track is.",
        "task_type": "anomaly_detection", "primary_approach": "train_model",
    }
    assert [f["title"] for f in shown["core_features"]] == ["Core 0", "Core 1", "Core 2"]
    assert "research" not in shown
    text = str(shown)
    assert "https://" not in text
    assert "Harbor Systems" not in text                     # organizations are never shown


async def test_a_research_shows_the_request_and_the_previous_names():
    previous, _ = await check(GOOD_PLAN)
    shown = build_llm_input(dataset_input(DatasetPreference.OWN_DATA, previous), await candidates())
    assert "own data" in shown["research"]["student_request"]
    assert shown["research"]["previous_answer"] == {
        "primary": "Vessel AIS tracks with labelled anomalies", "alternative": "Port traffic records",
    }


def test_the_prompt_asks_for_two_options_and_no_invented_facts():
    assert "exactly TWO options" in INSTRUCTIONS
    assert "Never invent facts" in INSTRUCTIONS
    assert NOT_STATED in INSTRUCTIONS
    for kind in DatasetKind:
        assert kind.value in INSTRUCTIONS


# ── Good replies ──────────────────────────────────────────────────────────────

async def test_a_good_reply_becomes_a_plan_with_the_found_links():
    plan, reason = await check(GOOD_PLAN)
    assert reason is None
    assert plan.primary.url == "https://www.kaggle.com/datasets/someone/vessel-ais-anomalies"
    assert plan.primary.source == "Kaggle"
    assert plan.primary.size == "12,000 labelled vessel tracks"
    assert plan.primary.license == "CC BY 4.0"
    assert plan.alternative.url == "https://zenodo.org/records/7654321"
    assert plan.alternative.source == "zenodo.org"
    assert plan.alternative.license == NOT_STATED


async def test_not_stated_variants_are_normalized():
    plan, _ = await check(bad(lambda r: r["primary"].update(size="not stated", license="Unknown", labels="Not stated.")))
    assert plan.primary.size == plan.primary.license == plan.primary.labels == NOT_STATED


async def test_own_data_has_no_link_and_says_how_to_get_it():
    plan, reason = await check(bad(lambda r: r.update(alternative=copy.deepcopy(OWN))))
    assert reason is None
    assert plan.alternative.kind == DatasetKind.SYNTHETIC
    assert plan.alternative.url is None
    assert plan.alternative.source == "You"
    assert plan.alternative.how_to_get.startswith("Write a small simulator")


# ── Bad replies ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("change, reason", [
    (lambda r: r["primary"].update(kind="scraped"), "unknown_choice"),
    (lambda r: r["primary"].update(fit="perfect"), "unknown_choice"),
    (lambda r: r["primary"].update(candidate_number=9), "unknown_candidate"),
    (lambda r: r["primary"].update(candidate_number=0), "unknown_candidate"),
    (lambda r: r["primary"].update(name="  "), "empty"),
    (lambda r: r.update(purpose=""), "empty"),
    (lambda r: r["primary"].update(main_features=[]), "wrong_count"),
    (lambda r: r["primary"].update(limitations=["a", "b", "c", "d", "e", "f"]), "wrong_count"),
    (lambda r: r["primary"].update(size="About 50,000 tracks"), "unsupported_fact"),
    (lambda r: r["primary"].update(license="MIT"), "unsupported_fact"),
    (lambda r: r["alternative"].update(license="Open Government Licence"), "unsupported_fact"),
    (lambda r: r["primary"].update(relevance="See kaggle.com for details."), "contains_url"),
    (lambda r: r["primary"].update(relevance="x" * 600), "too_long"),
    (lambda r: r.update(alternative=dict(OWN, how_to_get="")), "missing_how_to_get"),
    (lambda r: r["alternative"].update(candidate_number=1, name="Other name"), "same_dataset"),
    (lambda r: r.update(alternative=dict(OWN, name="Vessel AIS tracks with labelled anomalies")), "same_dataset"),
])
async def test_bad_replies_are_rejected(change, reason):
    plan, rejected = await check(bad(change))
    assert plan is None
    assert rejected == reason


async def test_own_data_must_be_primary_when_the_student_asks_for_it():
    previous, _ = await check(GOOD_PLAN)
    _, reason = await check(GOOD_PLAN, dataset_input(DatasetPreference.OWN_DATA, previous))
    assert reason == "own_data_not_primary"
    plan, reason = await check(
        {"purpose": "p", "primary": copy.deepcopy(OWN), "alternative": option()},
        dataset_input(DatasetPreference.OWN_DATA, previous),
    )
    assert reason is None and plan.primary.kind == DatasetKind.SYNTHETIC


# ── Running the skill ─────────────────────────────────────────────────────────

async def test_the_skill_searches_chooses_and_checks():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_PLAN])
    search = ScriptedSearch(PAGES)
    output, progress = await collect(FindDatasetsSkill(search, gateway), dataset_input())

    assert output.plan.primary.name == "Vessel AIS tracks with labelled anomalies"
    assert len(output.candidates) == 2
    assert output.searches_used == 4 and len(search.queries) == 4
    assert output.prompt_version == PROMPT_VERSION
    assert output.provider == "fake" and output.rejection_summary == {}
    assert [p.phase for p in progress] == [DatasetPhase.SEARCHING, DatasetPhase.CHOOSING, DatasetPhase.CHECKING]
    call = fake.calls[0]
    assert call.schema_name == "LLMDatasetPlanDraft"


async def test_the_search_budget_is_passed_on():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [GOOD_PLAN])
    search = ScriptedSearch(PAGES)
    output = await FindDatasetsSkill(search, gateway, max_searches=2).execute(dataset_input())
    assert output.searches_used == 2 and len(search.queries) == 2


async def test_a_bad_reply_is_retried_once():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [bad(lambda r: r["primary"].update(license="MIT")), GOOD_PLAN])
    output = await FindDatasetsSkill(ScriptedSearch(PAGES), gateway).execute(dataset_input())
    assert output.rejection_summary == {"unsupported_fact": 1}
    assert "feedback_from_previous_attempt" in str(fake.calls[1].input_json)


async def test_two_bad_replies_give_up():
    gateway, fake = gateway_and_fake()
    broken = bad(lambda r: r["primary"].update(candidate_number=7))
    fake.script("fake-model", [broken, broken])
    with pytest.raises(DatasetPlanRejectedError) as raised:
        await FindDatasetsSkill(ScriptedSearch(PAGES), gateway).execute(dataset_input())
    assert raised.value.rejection_summary == {"unknown_candidate": 2}
    assert raised.value.searches_used == 4


async def test_when_every_search_fails_the_skill_says_so():
    gateway, fake = gateway_and_fake()
    with pytest.raises(DatasetsUnavailableError):
        await FindDatasetsSkill(ScriptedSearch(error=SearchUnavailable("down")), gateway).execute(dataset_input())
    assert fake.calls == []                                     # the model is never asked


async def test_llm_failures_are_passed_on():
    gateway, fake = gateway_and_fake()
    fake.script("fake-model", [LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await FindDatasetsSkill(ScriptedSearch(PAGES), gateway).execute(dataset_input())


async def test_other_options_skips_the_datasets_shown_before():
    gateway, fake = gateway_and_fake()
    previous, _ = await check(GOOD_PLAN)
    known = await candidates()
    fake.script("fake-model", [{"purpose": "p", "primary": copy.deepcopy(OWN),
                                "alternative": dict(OWN, kind="student_collected", name="Collected tracks")}])
    search = ScriptedSearch(PAGES)                             # finds the same two pages again
    output = await FindDatasetsSkill(search, gateway).execute(
        dataset_input(DatasetPreference.OTHER_OPTIONS, previous, known=known)
    )
    assert output.candidates == []                             # both were shown before
    assert len(search.queries) == 3


async def test_own_data_reuses_the_pages_found_before():
    gateway, fake = gateway_and_fake()
    previous, _ = await check(GOOD_PLAN)
    fake.script("fake-model", [{"purpose": "p", "primary": copy.deepcopy(OWN), "alternative": option()}])
    search = ScriptedSearch(PAGES)
    output, progress = await collect(
        FindDatasetsSkill(search, gateway),
        dataset_input(DatasetPreference.OWN_DATA, previous, known=await candidates()),
    )
    assert search.queries == [] and output.searches_used == 0
    assert output.plan.alternative.url == PAGES[0].url
    assert progress[0].label == "Looking at the datasets found before"


# ── Fake mode ─────────────────────────────────────────────────────────────────

async def test_fake_answers_pass_the_checks_in_every_situation():
    found = await candidates()
    two = build_llm_input(dataset_input(), found)
    one = build_llm_input(dataset_input(), found[:1])
    none = build_llm_input(dataset_input(strategy=rule_based_strategy()), [])
    for llm_input, cands in [(two, found), (one, found[:1]), (none, [])]:
        plan, reason = check_plan_draft(LLMDatasetPlanDraft(**fake_dataset_plan(llm_input)), dataset_input(), cands)
        assert reason is None, reason
    no_ai_plan, _ = check_plan_draft(LLMDatasetPlanDraft(**fake_dataset_plan(none)), dataset_input(), [])
    assert "doesn't use AI" in no_ai_plan.purpose
    assert {no_ai_plan.primary.kind, no_ai_plan.alternative.kind} == {DatasetKind.SYNTHETIC, DatasetKind.STUDENT_COLLECTED}

    previous, _ = check_plan_draft(LLMDatasetPlanDraft(**fake_dataset_plan(two)), dataset_input(), found)
    own_input = dataset_input(DatasetPreference.OWN_DATA, previous)
    own_plan, reason = check_plan_draft(
        LLMDatasetPlanDraft(**fake_dataset_plan(build_llm_input(own_input, found))), own_input, found
    )
    assert reason is None and own_plan.primary.kind == DatasetKind.SYNTHETIC


async def test_skill_is_registered_and_answers_in_fake_mode():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")),
                        max_dataset_searches=3)
    skill = registry.get("find_datasets")
    output = await skill.execute(dataset_input(strategy=ml_strategy(necessity=AINecessity.TRADITIONAL_ML)))
    assert output.searches_used == 3
    assert output.plan.primary.kind == DatasetKind.PUBLIC
    assert output.plan.primary.url.startswith("https://") and ".example" in output.plan.primary.url


def test_skill_without_a_gateway_is_not_registered():
    registry = SkillRegistry()
    register_fyp_skills(registry, MockSearchProvider())
    assert "find_datasets" not in registry
