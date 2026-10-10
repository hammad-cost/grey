"""
Tests for dataset discovery storage in the Project Brain (Release 0.8, Step 1).

Covers the dataset rules (dataset_rules.py), the search runs and the pages
they found, saving the first recommendation, re-searches with a preference
(and their limits), the student's selection, and that each step only works
at the right stage.

Uses an in-memory SQLite database so no files are created on disk.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect

from app.core.brain.dataset_rules import DatasetRuleError, plan_rule_broken, research_problem
from app.core.brain.models import DatasetRunRecord
from app.core.brain.repository import DatasetError, DatasetRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_DATASET_RESEARCHES,
    NOT_STATED,
    DatasetCandidate,
    DatasetChoice,
    DatasetFit,
    DatasetKind,
    DatasetOption,
    DatasetPlan,
    DatasetPlanStatus,
    DatasetPreference,
    DatasetRunStatus,
    WorkflowState,
)
from tests.unit.test_brain_ai_strategy import checked
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)


def candidate(n: int) -> DatasetCandidate:
    return DatasetCandidate(
        title=f"Vessel tracks dataset {n}",
        url=f"https://data.example/datasets/vessel-tracks-{n}",
        snippet="Anonymised vessel position records with labelled unusual tracks.",
        publisher="Open Data Portal (sample)",
        query='"vessel tracks" anomaly detection dataset',
        provider="mock",
    )


CANDIDATES = [candidate(1), candidate(2), candidate(3), candidate(4)]


def public(n: int, **changes) -> DatasetOption:
    values = dict(
        kind=DatasetKind.PUBLIC,
        name=f"Vessel tracks dataset {n}",
        source="Open Data Portal (sample)",
        url=f"https://data.example/datasets/vessel-tracks-{n}",
        size=NOT_STATED,
        main_features=["Position", "Speed", "Heading"],
        labels="Unusual tracks are marked",
        license=NOT_STATED,
        relevance="It holds the vessel tracks the anomaly checker must score.",
        preprocessing=["Remove duplicate positions"],
        limitations=["Only one region"],
        fit=DatasetFit.GOOD,
    )
    values.update(changes)
    return DatasetOption(**values)


def own_data(**changes) -> DatasetOption:
    values = dict(
        kind=DatasetKind.SYNTHETIC,
        name="Simulated vessel tracks",
        source="You",
        size="As many tracks as you generate",
        main_features=["Position", "Speed"],
        labels="You mark the unusual tracks you simulate",
        license="Yours",
        relevance="You control which unusual patterns appear.",
        preprocessing=["Check the simulated tracks look realistic"],
        limitations=["May miss patterns seen in real data"],
        fit=DatasetFit.PARTIAL,
        how_to_get="Write a small simulator that moves vessels along routes and adds unusual detours.",
    )
    values.update(changes)
    return DatasetOption(**values)


def plan(primary: DatasetOption | None = None, alternative: DatasetOption | None = None) -> DatasetPlan:
    return DatasetPlan(
        purpose="Train and test the track checker.",
        primary=primary or public(1),
        alternative=alternative or public(2),
    )


URLS = {c.url for c in CANDIDATES}


async def strategy_approved(repo, workspace_id: str = WS):
    """A project whose AI strategy is approved (stage AI_STRATEGY_APPROVED)."""
    strategy = await checked(repo, workspace_id=workspace_id)
    return await repo.approve_ai_strategy(workspace_id, strategy.id)


async def searched(repo, recommendation: DatasetPlan | None = None, workspace_id: str = WS):
    """A project with a draft dataset recommendation (stage DATASET_DISCOVERY)."""
    await strategy_approved(repo, workspace_id)
    run = await repo.start_dataset_run(workspace_id)
    return await repo.complete_dataset_run(run.id, recommendation or plan(), CANDIDATES, searches_used=4, **LLM)


async def researched(repo, preference: DatasetPreference, recommendation: DatasetPlan, workspace_id: str = WS):
    run = await repo.start_dataset_run(workspace_id, preference)
    return await repo.complete_dataset_run(run.id, recommendation, CANDIDATES, searches_used=3, **LLM)


# ── Rules (plain code) ────────────────────────────────────────────────────────

def test_honest_plans_pass():
    assert plan_rule_broken(plan(), URLS) is None
    assert plan_rule_broken(plan(alternative=own_data()), URLS) is None
    assert plan_rule_broken(plan(own_data(), public(1)), URLS, preference=DatasetPreference.OWN_DATA) is None


@pytest.mark.parametrize("recommendation, rule", [
    (plan(public(1, url="https://invented.example/data")), "link_not_found_by_search"),
    (plan(public(1, url=None)), "missing_link"),
    (plan(alternative=own_data(url="https://data.example/datasets/vessel-tracks-3")), "link_for_own_data"),
    (plan(alternative=own_data(how_to_get=None)), "missing_how_to_get"),
    (plan(public(1), public(1)), "same_dataset"),
    (plan(public(1), public(2, name="  vessel TRACKS dataset 1 ")), "same_dataset"),
])
def test_dishonest_plans_are_caught(recommendation, rule):
    assert plan_rule_broken(recommendation, URLS) == rule


def test_preference_rules():
    assert plan_rule_broken(plan(), URLS, preference=DatasetPreference.OWN_DATA) == "own_data_not_primary"
    previous = plan()
    assert plan_rule_broken(
        plan(public(3), public(2)), URLS, preference=DatasetPreference.OTHER_OPTIONS, previous=previous
    ) == "repeated_dataset"
    assert plan_rule_broken(
        plan(public(3), public(4)), URLS, preference=DatasetPreference.OTHER_OPTIONS, previous=previous
    ) is None


def test_research_rules():
    assert research_problem(plan(), DatasetPreference.OWN_DATA) is None
    assert research_problem(plan(), DatasetPreference.OTHER_OPTIONS) is None
    assert "already data you create" in research_problem(plan(own_data(), public(1)), DatasetPreference.OWN_DATA)
    assert research_problem(plan(own_data(), public(1)), DatasetPreference.OTHER_OPTIONS) is None


def test_the_new_stages_come_in_blueprint_order():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.AI_STRATEGY_APPROVED) < stages.index(WorkflowState.DATASET_DISCOVERY)
    assert stages.index(WorkflowState.DATASET_DISCOVERY) + 1 == stages.index(WorkflowState.DATASET_SELECTED)
    assert stages.index(WorkflowState.DATASET_SELECTED) < stages.index(WorkflowState.TECHNOLOGY_PLAN)


# ── Tables ────────────────────────────────────────────────────────────────────

async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"dataset_run", "dataset_plan"} <= set(names)


# ── First search ──────────────────────────────────────────────────────────────

async def test_the_first_search_saves_a_draft_and_moves_to_review(repo):  # noqa: F811
    strategy = await strategy_approved(repo)
    run = await repo.start_dataset_run(WS)
    assert run.status == DatasetRunStatus.RUNNING
    assert run.preference is None
    assert run.strategy_id == strategy.id

    saved = await repo.complete_dataset_run(
        run.id, plan(), CANDIDATES, searches_used=4, plan_id="plan-1", **LLM
    )
    assert saved.id == "plan-1"
    assert saved.status == DatasetPlanStatus.DRAFT
    assert saved.plan == plan()
    assert saved.researches_used == 0
    assert saved.selected is None and saved.selected_option is None

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.DATASET_DISCOVERY
    assert snapshot.dataset_plan.id == "plan-1"
    assert snapshot.dataset_run.status == DatasetRunStatus.COMPLETE
    assert snapshot.dataset_run.searches_used == 4
    assert snapshot.dataset_run.candidates_found == 4
    assert snapshot.dataset_run.prompt_version == LLM["prompt_version"]
    assert await repo.list_dataset_candidates(run.id) == CANDIDATES


async def test_searching_before_the_ai_strategy_is_approved_is_refused(repo):  # noqa: F811
    await checked(repo)                                   # AI strategy still a draft
    with pytest.raises(DatasetError, match="after the AI strategy is approved"):
        await repo.start_dataset_run(WS)


async def test_searching_twice_is_refused(repo):  # noqa: F811
    await searched(repo)
    with pytest.raises(DatasetError):
        await repo.start_dataset_run(WS)


async def test_a_failed_search_can_be_retried(repo):  # noqa: F811
    await strategy_approved(repo)
    run = await repo.start_dataset_run(WS)
    failed = await repo.fail_dataset_run(run.id, "SearchUnavailable: all providers failed", searches_used=2)
    assert failed.status == DatasetRunStatus.FAILED
    assert failed.searches_used == 2
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.AI_STRATEGY_APPROVED

    retry = await repo.start_dataset_run(WS)
    await repo.complete_dataset_run(retry.id, plan(), CANDIDATES, searches_used=4, **LLM)
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.DATASET_DISCOVERY


async def test_a_second_search_while_one_runs_is_refused(repo):  # noqa: F811
    await strategy_approved(repo)
    await repo.start_dataset_run(WS)
    with pytest.raises(DatasetRunAlreadyRunningError):
        await repo.start_dataset_run(WS)


async def test_a_stale_running_search_is_replaced(repo, session):  # noqa: F811
    await strategy_approved(repo)
    stale = await repo.start_dataset_run(WS)
    record = await session.get(DatasetRunRecord, stale.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()

    fresh = await repo.start_dataset_run(WS)
    assert fresh.id != stale.id
    assert (await session.get(DatasetRunRecord, stale.id)).status == DatasetRunStatus.FAILED.value


async def test_a_plan_with_an_invented_link_is_not_saved(repo):  # noqa: F811
    await strategy_approved(repo)
    run = await repo.start_dataset_run(WS)
    with pytest.raises(DatasetRuleError):
        await repo.complete_dataset_run(
            run.id, plan(public(1, url="https://invented.example/data")), CANDIDATES, searches_used=4, **LLM
        )
    assert (await repo.get_snapshot(WS)).dataset_plan is None


async def test_a_finished_run_cannot_be_completed_again(repo):  # noqa: F811
    await strategy_approved(repo)
    run = await repo.start_dataset_run(WS)
    await repo.complete_dataset_run(run.id, plan(), CANDIDATES, searches_used=4, **LLM)
    with pytest.raises(ValueError, match="not running"):
        await repo.complete_dataset_run(run.id, plan(), CANDIDATES, searches_used=4, **LLM)


# ── Re-searches ───────────────────────────────────────────────────────────────

async def test_a_research_replaces_the_draft_and_uses_one_up(repo):  # noqa: F811
    first = await searched(repo)
    run = await repo.start_dataset_run(WS, DatasetPreference.OTHER_OPTIONS)
    assert run.preference == DatasetPreference.OTHER_OPTIONS

    replaced = await repo.complete_dataset_run(
        run.id, plan(public(3), public(4)), CANDIDATES, searches_used=3, **LLM
    )
    assert replaced.id == first.id                 # one recommendation per project
    assert replaced.plan.primary.name == "Vessel tracks dataset 3"
    assert replaced.researches_used == 1
    assert replaced.preference == DatasetPreference.OTHER_OPTIONS
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.DATASET_DISCOVERY


async def test_other_options_must_not_repeat_a_dataset(repo):  # noqa: F811
    await searched(repo)
    run = await repo.start_dataset_run(WS, DatasetPreference.OTHER_OPTIONS)
    with pytest.raises(DatasetRuleError, match="repeated_dataset"):
        await repo.complete_dataset_run(run.id, plan(public(1), public(3)), CANDIDATES, searches_used=3, **LLM)


async def test_own_data_must_become_the_primary_choice(repo):  # noqa: F811
    await searched(repo)
    run = await repo.start_dataset_run(WS, DatasetPreference.OWN_DATA)
    with pytest.raises(DatasetRuleError, match="own_data_not_primary"):
        await repo.complete_dataset_run(run.id, plan(), CANDIDATES, searches_used=0, **LLM)


async def test_own_data_is_not_offered_when_it_is_already_the_primary(repo):  # noqa: F811
    await searched(repo, plan(own_data(), public(1)))
    with pytest.raises(DatasetError, match="already data you create"):
        await repo.start_dataset_run(WS, DatasetPreference.OWN_DATA)


async def test_researches_are_limited(repo):  # noqa: F811
    await searched(repo)
    await researched(repo, DatasetPreference.OTHER_OPTIONS, plan(public(3), public(4)))
    await researched(repo, DatasetPreference.OWN_DATA, plan(own_data(), public(3)))
    assert MAX_DATASET_RESEARCHES == 2
    with pytest.raises(DatasetError, match="new searches have been used"):
        await repo.start_dataset_run(WS, DatasetPreference.OTHER_OPTIONS)


async def test_a_failed_research_does_not_use_one_up(repo):  # noqa: F811
    await searched(repo)
    run = await repo.start_dataset_run(WS, DatasetPreference.OTHER_OPTIONS)
    await repo.fail_dataset_run(run.id, "boom")
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.dataset_plan.researches_used == 0
    assert snapshot.dataset_plan.plan == plan()
    assert snapshot.workflow_state == WorkflowState.DATASET_DISCOVERY


async def test_research_before_any_recommendation_is_refused(repo):  # noqa: F811
    await strategy_approved(repo)
    with pytest.raises(DatasetError, match="no datasets to search again"):
        await repo.start_dataset_run(WS, DatasetPreference.OTHER_OPTIONS)


# ── Selection ─────────────────────────────────────────────────────────────────

async def test_selecting_the_alternative_ends_the_stage(repo):  # noqa: F811
    saved = await searched(repo)
    selected = await repo.select_dataset(WS, saved.id, DatasetChoice.ALTERNATIVE)
    assert selected.status == DatasetPlanStatus.SELECTED
    assert selected.selected == DatasetChoice.ALTERNATIVE
    assert selected.selected_option == plan().alternative
    assert selected.selected_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.DATASET_SELECTED


async def test_selecting_with_a_wrong_id_is_refused(repo):  # noqa: F811
    await searched(repo)
    with pytest.raises(DatasetError, match="not this project's"):
        await repo.select_dataset(WS, "someone-else", DatasetChoice.PRIMARY)


async def test_nothing_changes_after_selection(repo):  # noqa: F811
    saved = await searched(repo)
    await repo.select_dataset(WS, saved.id, DatasetChoice.PRIMARY)
    with pytest.raises(DatasetError):
        await repo.select_dataset(WS, saved.id, DatasetChoice.ALTERNATIVE)
    with pytest.raises(DatasetError):
        await repo.start_dataset_run(WS, DatasetPreference.OTHER_OPTIONS)


async def test_selecting_before_any_recommendation_is_refused(repo):  # noqa: F811
    await strategy_approved(repo)
    with pytest.raises(DatasetError, match="no datasets to select"):
        await repo.select_dataset(WS, "plan-1", DatasetChoice.PRIMARY)
