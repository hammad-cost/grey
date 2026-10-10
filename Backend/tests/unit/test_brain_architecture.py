"""
Tests for architecture and evaluation plan storage in the Project Brain (Release 0.11, Step 1).
"""
import pytest
from sqlalchemy import inspect

from app.core.brain.architecture_rules import ArchitectureRuleError, allowed_metrics, plan_rule_broken
from app.core.brain.repository import ArchitectureError, ArchitectureRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_ARCHITECTURE_REDESIGNS,
    AITaskType,
    Architecture,
    ArchitectureComponent,
    ArchitectureFlow,
    ArchitecturePreference,
    ArchitectureRunStatus,
    ComponentKind,
    EvaluationMetric,
    EvaluationPlan,
    Metric,
    SystemTest,
    SystemTestKind,
    TechnicalPlan,
    TechnicalPlanStatus,
    WorkflowState,
)
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)
from tests.unit.test_brain_technology import planned

KINDS = [ComponentKind.DATA_SOURCE, ComponentKind.MODEL, ComponentKind.BACKEND, ComponentKind.INTERFACE, ComponentKind.USER]


def components(kinds=KINDS) -> list[ArchitectureComponent]:
    return [ArchitectureComponent(id=f"c{n}", name=f"Part {n}", kind=k, role="Does a job") for n, k in enumerate(kinds, 1)]


def chain(n: int) -> list[ArchitectureFlow]:
    return [ArchitectureFlow(source=f"c{i}", target=f"c{i + 1}", data="data") for i in range(1, n)]


def tech_plan(kinds=KINDS, flows=None, metrics=(Metric.RECALL, Metric.PRECISION), tests=None, baseline=None) -> TechnicalPlan:
    return TechnicalPlan(
        summary="Tracks go through a model to a dashboard.",
        architecture=Architecture(components=components(kinds), flows=flows or chain(len(kinds))),
        evaluation=EvaluationPlan(
            metrics=[EvaluationMetric(metric=m, why="It matters.", goal="As high as possible") for m in metrics],
            tests=tests or [SystemTest(kind=SystemTestKind.FUNCTIONAL_TESTING, how="Test each feature.")],
            baseline=baseline,
        ),
    )


NO_AI_KINDS = [ComponentKind.DATA_SOURCE, ComponentKind.RULES, ComponentKind.INTERFACE, ComponentKind.USER]


async def technology_approved(repo):  # noqa: F811
    saved = await planned(repo)
    return await repo.approve_technology_plan(WS, saved.id)


async def designed(repo, plan=None):  # noqa: F811
    await technology_approved(repo)
    run = await repo.start_architecture_run(WS)
    return await repo.complete_architecture_run(run.id, plan or tech_plan(), **LLM)


# ── Rules ─────────────────────────────────────────────────────────────────────

def test_consistent_plans_pass():
    assert plan_rule_broken(tech_plan(), uses_ai=True, task=AITaskType.ANOMALY_DETECTION) is None
    assert plan_rule_broken(tech_plan(NO_AI_KINDS, metrics=()), uses_ai=False, task=None) is None
    assert plan_rule_broken(tech_plan(metrics=(Metric.MAE,)), uses_ai=True, task=AITaskType.FORECASTING) is None


def test_metric_families():
    assert allowed_metrics(AITaskType.REGRESSION) == {Metric.MAE, Metric.RMSE}
    assert Metric.RMSE not in allowed_metrics(AITaskType.CLASSIFICATION)
    assert allowed_metrics(AITaskType.RECOMMENDATION) == set(Metric)


@pytest.mark.parametrize("plan, uses_ai, task, rule", [
    (tech_plan([ComponentKind.DATA_SOURCE] * 2 + KINDS[2:], flows=chain(4) + [ArchitectureFlow(source="c1", target="c1", data="x")]),
     True, None, "unknown_component"),
    (tech_plan(flows=chain(3) + [ArchitectureFlow(source="c3", target="c9", data="x")]), True, None, "unknown_component"),
    (tech_plan(flows=chain(4)), True, None, "unconnected_component"),
    (tech_plan([ComponentKind.DATA_SOURCE, ComponentKind.MODEL, ComponentKind.BACKEND, ComponentKind.USER]),
     True, None, "missing_interface"),
    (tech_plan(NO_AI_KINDS), True, None, "missing_model"),
    (tech_plan(metrics=()), True, None, "missing_ai_metrics"),
    (tech_plan(metrics=(Metric.RMSE,)), True, AITaskType.ANOMALY_DETECTION, "metric_mismatch"),
    (tech_plan(metrics=(Metric.F1_SCORE,)), True, AITaskType.FORECASTING, "metric_mismatch"),
    (tech_plan(), False, None, "ai_without_ai"),
    (tech_plan(NO_AI_KINDS, metrics=(Metric.ACCURACY,)), False, None, "ai_without_ai"),
    (tech_plan(metrics=(Metric.RECALL, Metric.RECALL)), True, None, "duplicate_metric"),
    (tech_plan(tests=[SystemTest(kind=SystemTestKind.RESPONSE_TIME, how="h")] * 2), True, None, "duplicate_test"),
    (tech_plan(tests=[SystemTest(kind=SystemTestKind.BASELINE_COMPARISON, how="h")]), True, None, "missing_baseline"),
])
def test_inconsistent_plans_are_caught(plan, uses_ai, task, rule):
    assert plan_rule_broken(plan, uses_ai=uses_ai, task=task) == rule


def test_duplicate_component_ids_are_caught():
    plan = tech_plan()
    plan.architecture.components[1] = plan.architecture.components[1].model_copy(update={"id": "c1"})
    assert plan_rule_broken(plan, uses_ai=True, task=None) == "duplicate_component"


def test_the_new_stage_comes_in_order():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.TECHNOLOGY_APPROVED) < stages.index(WorkflowState.ARCHITECTURE)
    assert stages.index(WorkflowState.EVALUATION) + 1 == stages.index(WorkflowState.TECHNICAL_PLAN_APPROVED)
    assert stages.index(WorkflowState.TECHNICAL_PLAN_APPROVED) < stages.index(WorkflowState.FEASIBILITY)


async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"architecture_run", "technical_plan"} <= set(names)


# ── Plan, redesigns, approval ─────────────────────────────────────────────────

async def test_the_first_plan_saves_a_draft_and_moves_to_review(repo):  # noqa: F811
    technology = await technology_approved(repo)
    run = await repo.start_architecture_run(WS)
    assert run.status == ArchitectureRunStatus.RUNNING and run.technology_plan_id == technology.id
    saved = await repo.complete_architecture_run(run.id, tech_plan(), plan_id="a-1", **LLM)
    assert saved.id == "a-1" and saved.status == TechnicalPlanStatus.DRAFT
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.ARCHITECTURE
    assert len(snapshot.technical_plan.plan.architecture.components) == 5


async def test_designing_needs_an_approved_technology_plan_and_happens_once(repo):  # noqa: F811
    await planned(repo)
    with pytest.raises(ArchitectureError, match="after the technology plan is approved"):
        await repo.start_architecture_run(WS)
    await repo.approve_technology_plan(WS, (await repo.get_technology_plan(WS)).id)
    run = await repo.start_architecture_run(WS)
    with pytest.raises(ArchitectureRunAlreadyRunningError):
        await repo.start_architecture_run(WS)
    await repo.complete_architecture_run(run.id, tech_plan(), **LLM)
    with pytest.raises(ArchitectureError):
        await repo.start_architecture_run(WS)


async def test_a_plan_breaking_the_rules_is_not_saved(repo):  # noqa: F811
    await technology_approved(repo)
    run = await repo.start_architecture_run(WS)
    with pytest.raises(ArchitectureRuleError, match="metric_mismatch"):
        await repo.complete_architecture_run(run.id, tech_plan(metrics=(Metric.MAE,)), **LLM)   # anomaly detection
    failed = await repo.fail_architecture_run(run.id, "rule broken")
    assert failed.status == ArchitectureRunStatus.FAILED


async def test_redesigns_replace_the_draft_and_are_limited(repo):  # noqa: F811
    first = await designed(repo)
    for n in range(MAX_ARCHITECTURE_REDESIGNS):
        run = await repo.start_architecture_run(WS, ArchitecturePreference.SIMPLER)
        replaced = await repo.complete_architecture_run(run.id, tech_plan(), **LLM)
        assert replaced.id == first.id and replaced.redesigns_used == n + 1
    with pytest.raises(ArchitectureError, match="redesigns have been used"):
        await repo.start_architecture_run(WS, ArchitecturePreference.SIMPLER)


async def test_approval_ends_the_stage(repo):  # noqa: F811
    saved = await designed(repo)
    with pytest.raises(ArchitectureError, match="not this project's"):
        await repo.approve_technical_plan(WS, "nope")
    approved = await repo.approve_technical_plan(WS, saved.id)
    assert approved.status == TechnicalPlanStatus.APPROVED
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.TECHNICAL_PLAN_APPROVED
    with pytest.raises(ArchitectureError):
        await repo.start_architecture_run(WS, ArchitecturePreference.SIMPLER)
