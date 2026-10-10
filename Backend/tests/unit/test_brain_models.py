"""
Tests for pretrained-model and API storage in the Project Brain (Release 0.9, Step 1).

Covers the model rules (model_rules.py), the search runs and the pages they
found, saving the first plan, re-searches (and their limits), approval, and
that each step only works at the right stage.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect

from app.core.brain.model_rules import ModelRuleError, plan_rule_broken, research_problem
from app.core.brain.models import ModelRunRecord
from app.core.brain.repository import ModelError, ModelRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_MODEL_RESEARCHES,
    DatasetChoice,
    ModelCandidate,
    ModelKind,
    ModelOption,
    ModelPlan,
    ModelPlanStatus,
    ModelPreference,
    ModelRunStatus,
    ModelUse,
    WorkflowState,
)
from tests.unit.test_brain_datasets import searched
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)


def page(n: int) -> ModelCandidate:
    return ModelCandidate(
        title=f"Track anomaly model {n}",
        url=f"https://huggingface.co/someone/track-anomaly-{n}",
        snippet="A pretrained model that scores vessel tracks.",
        publisher="huggingface.co",
        query="Navy anomaly detection pretrained model",
        provider="mock",
    )


PAGES = [page(1), page(2), page(3), page(4)]
URLS = {p.url for p in PAGES}


def option(n: int, **changes) -> ModelOption:
    values = dict(
        kind=ModelKind.PRETRAINED_MODEL,
        name=f"Track anomaly model {n}",
        source="huggingface.co",
        url=f"https://huggingface.co/someone/track-anomaly-{n}",
        use=ModelUse.BENCHMARK,
        reason="Compare your own model with it.",
        role="The track checker",
        limitations=["Trained on another region"],
    )
    values.update(changes)
    return ModelOption(**values)


def plan(*options: ModelOption, needs_model: bool = True) -> ModelPlan:
    return ModelPlan(needs_model=needs_model, summary="One model is worth comparing against.", options=list(options))


NO_AI_PLAN = ModelPlan(needs_model=False, summary="Your project doesn't use AI, so no model is needed.")


async def dataset_selected(repo, workspace_id: str = WS):
    """A project whose dataset is selected (stage DATASET_SELECTED)."""
    saved = await searched(repo, workspace_id=workspace_id)
    return await repo.select_dataset(workspace_id, saved.id, DatasetChoice.PRIMARY)


async def looked(repo, model_plan: ModelPlan | None = None, workspace_id: str = WS):
    """A project with a draft model plan (stage MODEL_SELECTION)."""
    await dataset_selected(repo, workspace_id)
    run = await repo.start_model_run(workspace_id)
    return await repo.complete_model_run(run.id, model_plan or plan(option(1), option(2)), PAGES, searches_used=4, **LLM)


# ── Rules ─────────────────────────────────────────────────────────────────────

def test_honest_plans_pass():
    assert plan_rule_broken(plan(option(1), option(2)), URLS) is None
    assert plan_rule_broken(plan(), URLS) is None                     # nothing relevant found
    assert plan_rule_broken(NO_AI_PLAN, set()) is None


@pytest.mark.parametrize("model_plan, rule", [
    (plan(option(1, url="https://invented.example/model")), "link_not_found_by_search"),
    (plan(option(1), option(1)), "same_model"),
    (plan(option(1), needs_model=False), "options_without_ai"),
])
def test_dishonest_plans_are_caught(model_plan, rule):
    assert plan_rule_broken(model_plan, URLS) == rule


def test_other_options_never_repeat_a_page():
    previous = plan(option(1), option(2))
    assert plan_rule_broken(plan(option(2), option(3)), URLS, preference=ModelPreference.OTHER_OPTIONS,
                            previous=previous) == "repeated_model"
    assert plan_rule_broken(plan(option(3), option(4)), URLS, preference=ModelPreference.OTHER_OPTIONS,
                            previous=previous) is None


def test_research_rules():
    assert research_problem(plan(option(1)), ModelPreference.OTHER_OPTIONS) is None
    assert "doesn't use AI" in research_problem(NO_AI_PLAN, ModelPreference.OTHER_OPTIONS)


def test_the_new_stages_come_in_blueprint_order():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.DATASET_SELECTED) + 1 == stages.index(WorkflowState.MODEL_SELECTION)
    assert stages.index(WorkflowState.MODEL_SELECTION) + 1 == stages.index(WorkflowState.MODELS_APPROVED)
    assert stages.index(WorkflowState.MODELS_APPROVED) < stages.index(WorkflowState.TECHNOLOGY_PLAN)


async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"model_run", "model_plan"} <= set(names)


# ── First search ──────────────────────────────────────────────────────────────

async def test_the_first_search_saves_a_draft_and_moves_to_review(repo):  # noqa: F811
    dataset = await dataset_selected(repo)
    run = await repo.start_model_run(WS)
    assert run.status == ModelRunStatus.RUNNING and run.dataset_plan_id == dataset.id

    saved = await repo.complete_model_run(run.id, plan(option(1)), PAGES, searches_used=4, plan_id="m-1", **LLM)
    assert saved.id == "m-1" and saved.status == ModelPlanStatus.DRAFT
    assert saved.plan.options[0].use == ModelUse.BENCHMARK

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.MODEL_SELECTION
    assert snapshot.model_plan.id == "m-1"
    assert snapshot.model_run.candidates_found == 4 and snapshot.model_run.searches_used == 4
    assert await repo.list_model_candidates(run.id) == PAGES


async def test_a_no_ai_plan_is_saved_without_pages(repo):  # noqa: F811
    await dataset_selected(repo)
    run = await repo.start_model_run(WS)
    saved = await repo.complete_model_run(run.id, NO_AI_PLAN, [], searches_used=0,
                                          provider="grey", model="rules", prompt_version="none")
    assert saved.plan.needs_model is False
    with pytest.raises(ModelError, match="doesn't use AI"):
        await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)


async def test_searching_before_a_dataset_is_selected_is_refused(repo):  # noqa: F811
    await searched(repo)
    with pytest.raises(ModelError, match="after a dataset is selected"):
        await repo.start_model_run(WS)


async def test_searching_twice_is_refused(repo):  # noqa: F811
    await looked(repo)
    with pytest.raises(ModelError):
        await repo.start_model_run(WS)


async def test_a_failed_search_can_be_retried(repo):  # noqa: F811
    await dataset_selected(repo)
    run = await repo.start_model_run(WS)
    failed = await repo.fail_model_run(run.id, "boom", searches_used=2)
    assert failed.status == ModelRunStatus.FAILED and failed.searches_used == 2
    retry = await repo.start_model_run(WS)
    await repo.complete_model_run(retry.id, plan(option(1)), PAGES, searches_used=4, **LLM)
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.MODEL_SELECTION


async def test_one_search_at_a_time_and_stale_runs_are_replaced(repo, session):  # noqa: F811
    await dataset_selected(repo)
    stale = await repo.start_model_run(WS)
    with pytest.raises(ModelRunAlreadyRunningError):
        await repo.start_model_run(WS)
    record = await session.get(ModelRunRecord, stale.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()
    fresh = await repo.start_model_run(WS)
    assert fresh.id != stale.id
    assert (await session.get(ModelRunRecord, stale.id)).status == ModelRunStatus.FAILED.value


async def test_a_plan_with_an_invented_link_is_not_saved(repo):  # noqa: F811
    await dataset_selected(repo)
    run = await repo.start_model_run(WS)
    with pytest.raises(ModelRuleError):
        await repo.complete_model_run(run.id, plan(option(1, url="https://invented.example/m")), PAGES,
                                      searches_used=4, **LLM)
    assert (await repo.get_snapshot(WS)).model_plan is None


# ── Re-searches ───────────────────────────────────────────────────────────────

async def test_a_research_replaces_the_draft_and_uses_one_up(repo):  # noqa: F811
    first = await looked(repo)
    run = await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)
    replaced = await repo.complete_model_run(run.id, plan(option(3), option(4)), PAGES, searches_used=3, **LLM)
    assert replaced.id == first.id and replaced.researches_used == 1
    assert [o.name for o in replaced.plan.options] == ["Track anomaly model 3", "Track anomaly model 4"]


async def test_a_research_must_not_repeat_a_page(repo):  # noqa: F811
    await looked(repo)
    run = await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)
    with pytest.raises(ModelRuleError, match="repeated_model"):
        await repo.complete_model_run(run.id, plan(option(1)), PAGES, searches_used=3, **LLM)


async def test_researches_are_limited_and_failures_dont_count(repo):  # noqa: F811
    await looked(repo)
    run = await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)
    await repo.fail_model_run(run.id, "down")
    assert (await repo.get_model_plan(WS)).researches_used == 0
    for _ in range(MAX_MODEL_RESEARCHES):
        run = await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)
        await repo.complete_model_run(run.id, plan(), PAGES, searches_used=3, **LLM)
    with pytest.raises(ModelError, match="new searches have been used"):
        await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)


# ── Approval ──────────────────────────────────────────────────────────────────

async def test_approval_ends_the_stage_and_freezes_the_plan(repo):  # noqa: F811
    saved = await looked(repo)
    with pytest.raises(ModelError, match="not this project's"):
        await repo.approve_model_plan(WS, "someone-else")
    approved = await repo.approve_model_plan(WS, saved.id)
    assert approved.status == ModelPlanStatus.APPROVED and approved.approved_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.MODELS_APPROVED
    with pytest.raises(ModelError):
        await repo.approve_model_plan(WS, saved.id)
    with pytest.raises(ModelError):
        await repo.start_model_run(WS, ModelPreference.OTHER_OPTIONS)
