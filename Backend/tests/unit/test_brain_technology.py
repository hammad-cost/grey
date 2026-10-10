"""
Tests for technology stack and hardware storage in the Project Brain (Release 0.10, Step 1).
"""
import pytest
from sqlalchemy import inspect

from app.core.brain.repository import TechnologyError, TechnologyRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_TECHNOLOGY_REPLANS,
    CostLevel,
    HardwareItem,
    HardwareKind,
    StackArea,
    StackChoice,
    TechnologyPlan,
    TechnologyPlanStatus,
    TechnologyPreference,
    TechnologyRunStatus,
    WorkflowState,
)
from app.core.brain.technology_rules import TechnologyRuleError, plan_rule_broken
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_models import looked
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)


def choice(area: StackArea, name: str = "Tool") -> StackChoice:
    return StackChoice(area=area, choice=name, reason="It fits this project.")


LAPTOP = HardwareItem(kind=HardwareKind.NORMAL_LAPTOP, name="A normal laptop", purpose="Build and run the app",
                      essential=True, cost=CostLevel.NONE)


def tech_plan(*areas: StackArea, hardware=None) -> TechnologyPlan:
    areas = areas or (StackArea.FRONTEND, StackArea.BACKEND, StackArea.AI_ML)
    return TechnologyPlan(summary="A small web app with a trained model.",
                          stack=[choice(a) for a in areas], hardware=hardware or [LAPTOP])


async def models_approved(repo, workspace_id: str = WS):  # noqa: F811
    saved = await looked(repo, workspace_id=workspace_id)
    return await repo.approve_model_plan(workspace_id, saved.id)


async def planned(repo, plan: TechnologyPlan | None = None):  # noqa: F811
    await models_approved(repo)
    run = await repo.start_technology_run(WS)
    return await repo.complete_technology_run(run.id, plan or tech_plan(), **LLM)


# ── Rules ─────────────────────────────────────────────────────────────────────

def test_consistent_plans_pass():
    assert plan_rule_broken(tech_plan(), uses_ai=True) is None
    assert plan_rule_broken(tech_plan(StackArea.FRONTEND, StackArea.DATABASE), uses_ai=False) is None


@pytest.mark.parametrize("plan, uses_ai, rule", [
    (tech_plan(StackArea.FRONTEND, StackArea.FRONTEND, StackArea.AI_ML), True, "duplicate_area"),
    (tech_plan(StackArea.FRONTEND, StackArea.BACKEND), True, "missing_ai_ml"),
    (tech_plan(StackArea.FRONTEND, StackArea.AI_ML), False, "ai_without_ai"),
    (tech_plan(StackArea.FRONTEND, StackArea.TRAINING), False, "ai_without_ai"),
    (tech_plan(StackArea.DATABASE, StackArea.AI_ML), True, "no_application"),
    (tech_plan(hardware=[LAPTOP.model_copy(update={"kind": HardwareKind.CLOUD_GPU, "cost": CostLevel.HIGH})]),
     True, "missing_alternative"),
])
def test_inconsistent_plans_are_caught(plan, uses_ai, rule):
    assert plan_rule_broken(plan, uses_ai=uses_ai) == rule


def test_the_new_stage_comes_in_order():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.MODELS_APPROVED) + 1 == stages.index(WorkflowState.TECHNOLOGY_PLAN)
    assert stages.index(WorkflowState.TECHNOLOGY_PLAN) + 1 == stages.index(WorkflowState.TECHNOLOGY_APPROVED)


async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"technology_run", "technology_plan"} <= set(names)


# ── Plan, re-plans, approval ──────────────────────────────────────────────────

async def test_the_first_plan_saves_a_draft_and_moves_to_review(repo):  # noqa: F811
    models = await models_approved(repo)
    run = await repo.start_technology_run(WS)
    assert run.status == TechnologyRunStatus.RUNNING and run.model_plan_id == models.id
    saved = await repo.complete_technology_run(run.id, tech_plan(), plan_id="t-1", **LLM)
    assert saved.id == "t-1" and saved.status == TechnologyPlanStatus.DRAFT
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.TECHNOLOGY_PLAN
    assert snapshot.technology_plan.plan.stack[0].area == StackArea.FRONTEND
    assert snapshot.technology_run.status == TechnologyRunStatus.COMPLETE


async def test_planning_needs_an_approved_model_plan_and_happens_once(repo):  # noqa: F811
    await looked(repo)
    with pytest.raises(TechnologyError, match="after the model plan is approved"):
        await repo.start_technology_run(WS)
    await repo.approve_model_plan(WS, (await repo.get_model_plan(WS)).id)
    run = await repo.start_technology_run(WS)
    with pytest.raises(TechnologyRunAlreadyRunningError):
        await repo.start_technology_run(WS)
    await repo.complete_technology_run(run.id, tech_plan(), **LLM)
    with pytest.raises(TechnologyError):
        await repo.start_technology_run(WS)


async def test_a_plan_breaking_the_rules_is_not_saved(repo):  # noqa: F811
    await models_approved(repo)                     # the sample project uses AI
    run = await repo.start_technology_run(WS)
    with pytest.raises(TechnologyRuleError, match="missing_ai_ml"):
        await repo.complete_technology_run(run.id, tech_plan(StackArea.FRONTEND, StackArea.BACKEND), **LLM)
    failed = await repo.fail_technology_run(run.id, "rule broken")
    assert failed.status == TechnologyRunStatus.FAILED
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.MODELS_APPROVED


async def test_replans_replace_the_draft_and_are_limited(repo):  # noqa: F811
    first = await planned(repo)
    for n in range(MAX_TECHNOLOGY_REPLANS):
        run = await repo.start_technology_run(WS, TechnologyPreference.SIMPLER)
        replaced = await repo.complete_technology_run(run.id, tech_plan(), **LLM)
        assert replaced.id == first.id and replaced.replans_used == n + 1
        assert replaced.preference == TechnologyPreference.SIMPLER
    with pytest.raises(TechnologyError, match="re-plans have been used"):
        await repo.start_technology_run(WS, TechnologyPreference.SIMPLER)


async def test_approval_ends_the_stage(repo):  # noqa: F811
    saved = await planned(repo)
    with pytest.raises(TechnologyError, match="not this project's"):
        await repo.approve_technology_plan(WS, "nope")
    approved = await repo.approve_technology_plan(WS, saved.id)
    assert approved.status == TechnologyPlanStatus.APPROVED and approved.approved_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.TECHNOLOGY_APPROVED
    with pytest.raises(TechnologyError):
        await repo.start_technology_run(WS, TechnologyPreference.SIMPLER)
    with pytest.raises(TechnologyError):
        await repo.approve_technology_plan(WS, saved.id)
