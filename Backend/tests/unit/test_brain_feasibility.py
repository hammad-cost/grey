"""
Tests for feasibility storage and rules in the Project Brain (Release 0.12, Step 1).
"""
import pytest
from sqlalchemy import inspect

from app.core.brain.feasibility_rules import (
    FeasibilityRuleError,
    overall_feasibility,
    overall_reason,
    report_rule_broken,
)
from app.core.brain.repository import FeasibilityError, FeasibilityRunAlreadyRunningError
from app.core.brain.schemas import (
    AssessedBy,
    DimensionAssessment,
    FeasibilityDimension,
    FeasibilityLevel,
    FeasibilityReport,
    FeasibilityRisk,
    FeasibilityRunStatus,
    FeasibilityStatus,
    OverallFeasibility,
    WorkflowState,
)
from tests.unit.test_brain_architecture import designed
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)

F, M, C = FeasibilityLevel.FAVOURABLE, FeasibilityLevel.MODERATE, FeasibilityLevel.CONCERN


def dimensions(default=F, **levels) -> list[DimensionAssessment]:
    return [
        DimensionAssessment(dimension=d, level=levels.get(d.value, default), finding="ok", reason="because",
                            assessed_by=AssessedBy.FACTS)
        for d in FeasibilityDimension
    ]


def report(dims=None, overall=None) -> FeasibilityReport:
    dims = dims or dimensions()
    return FeasibilityReport(
        summary="Realistic for one student.", dimensions=dims,
        main_risks=[FeasibilityRisk(risk="Preprocessing takes long", mitigation="Start early")],
        overall=overall or overall_feasibility(dims), overall_reason=overall_reason(dims),
    )


# ── Rules ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dims, expected", [
    (dimensions(), OverallFeasibility.HIGH),
    (dimensions(M), OverallFeasibility.MEDIUM),
    (dimensions(C), OverallFeasibility.LOW),
    (dimensions(cost="concern", novelty="concern"), OverallFeasibility.HIGH),
    (dimensions(cost="concern", novelty="concern", risk="concern"), OverallFeasibility.LOW),
    (dimensions(time="concern"), OverallFeasibility.MEDIUM),                 # capped
    (dimensions(technical_complexity="concern"), OverallFeasibility.MEDIUM),  # capped
    (dimensions(M, problem_relevance="concern"), OverallFeasibility.LOW),     # average below 1.0
])
def test_the_overall_rating_is_computed(dims, expected):
    assert overall_feasibility(dims) == expected


def test_the_overall_reason_names_the_concerns():
    text = overall_reason(dimensions(time="concern"))
    assert text == "12 of 13 dimensions are favourable, 0 moderate and 1 a concern (time)."


def test_report_rules():
    assert report_rule_broken(report()) is None
    assert report_rule_broken(report(overall=OverallFeasibility.LOW)) == "overall_mismatch"
    dims = dimensions()
    dims[0] = dims[1]                                   # one dimension twice, one missing
    assert report_rule_broken(report(dims)) == "missing_dimension"


def test_the_new_stage_comes_in_order():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.TECHNICAL_PLAN_APPROVED) + 1 == stages.index(WorkflowState.FEASIBILITY)
    assert stages.index(WorkflowState.FEASIBILITY) + 1 == stages.index(WorkflowState.FEASIBILITY_ACCEPTED)


async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"feasibility_run", "feasibility_report"} <= set(names)


# ── Storage ───────────────────────────────────────────────────────────────────

async def plan_approved(repo):  # noqa: F811
    saved = await designed(repo)
    return await repo.approve_technical_plan(WS, saved.id)


async def test_the_report_is_saved_and_moves_to_review(repo):  # noqa: F811
    technical = await plan_approved(repo)
    run = await repo.start_feasibility_run(WS)
    assert run.status == FeasibilityRunStatus.RUNNING and run.technical_plan_id == technical.id
    with pytest.raises(FeasibilityRunAlreadyRunningError):
        await repo.start_feasibility_run(WS)
    saved = await repo.complete_feasibility_run(run.id, report(), report_id="f-1", **LLM)
    assert saved.id == "f-1" and saved.status == FeasibilityStatus.DRAFT
    assert saved.report.overall == OverallFeasibility.HIGH
    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.FEASIBILITY and snapshot.feasibility_run.status == FeasibilityRunStatus.COMPLETE
    with pytest.raises(FeasibilityError):
        await repo.start_feasibility_run(WS)


async def test_assessing_needs_an_approved_technical_plan(repo):  # noqa: F811
    await designed(repo)
    with pytest.raises(FeasibilityError, match="after the technical plan is approved"):
        await repo.start_feasibility_run(WS)


async def test_a_report_with_a_wrong_overall_is_not_saved_and_runs_can_fail(repo):  # noqa: F811
    await plan_approved(repo)
    run = await repo.start_feasibility_run(WS)
    with pytest.raises(FeasibilityRuleError, match="overall_mismatch"):
        await repo.complete_feasibility_run(run.id, report(overall=OverallFeasibility.LOW), **LLM)
    failed = await repo.fail_feasibility_run(run.id, "boom")
    assert failed.status == FeasibilityRunStatus.FAILED
    retry = await repo.start_feasibility_run(WS)
    await repo.complete_feasibility_run(retry.id, report(), **LLM)


async def test_accepting_ends_the_stage(repo):  # noqa: F811
    await plan_approved(repo)
    run = await repo.start_feasibility_run(WS)
    saved = await repo.complete_feasibility_run(run.id, report(), **LLM)
    with pytest.raises(FeasibilityError, match="not this project's"):
        await repo.accept_feasibility(WS, "nope")
    accepted = await repo.accept_feasibility(WS, saved.id)
    assert accepted.status == FeasibilityStatus.ACCEPTED and accepted.accepted_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.FEASIBILITY_ACCEPTED
    with pytest.raises(FeasibilityError):
        await repo.accept_feasibility(WS, saved.id)
