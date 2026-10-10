"""
Tests for supervisor brief storage and rules in the Project Brain (Release 0.13, Step 1).
"""
import pytest
from sqlalchemy import inspect

from app.core.brain.repository import ReadinessError, ReadinessRunAlreadyRunningError
from app.core.brain.schemas import (
    ReadinessCheck,
    ReadinessCheckId,
    ReadinessRunStatus,
    ReadinessStatus,
    SummaryItem,
    SupervisorBrief,
    SupervisorBriefStatus,
    SupervisorQuestion,
    SupervisorQuestionId,
    WorkflowState,
)
from app.core.brain.supervisor_rules import SupervisorBriefRuleError, brief_rule_broken
from tests.unit.test_brain_feasibility import plan_approved, report
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)


def brief(status=ReadinessStatus.PASS, checks=None, questions=None) -> SupervisorBrief:
    return SupervisorBrief(
        checks=checks or [ReadinessCheck(check=c, question="?", status=status, detail="d") for c in ReadinessCheckId],
        summary=[SummaryItem(label="Project title", value="Track alerts")],
        questions=questions or [
            SupervisorQuestion(id=q, question="?", talking_points=["a", "b"]) for q in SupervisorQuestionId
        ],
    )


def test_ready_means_every_check_passes():
    assert brief().ready is True
    checks = brief().checks
    checks[0] = checks[0].model_copy(update={"status": ReadinessStatus.ATTENTION})
    assert brief(checks=checks).ready is False


def test_brief_rules():
    assert brief_rule_broken(brief()) is None
    checks = brief().checks
    checks[0] = checks[1]
    assert brief_rule_broken(brief(checks=checks)) == "missing_check"
    questions = brief().questions
    questions[0] = questions[1]
    assert brief_rule_broken(brief(questions=questions)) == "missing_question"


def test_the_new_stage_comes_in_order():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.FEASIBILITY_ACCEPTED) + 1 == stages.index(WorkflowState.SUPERVISOR_READINESS)
    assert stages.index(WorkflowState.SUPERVISOR_READINESS) + 1 == stages.index(WorkflowState.SUPERVISOR_READY)
    assert stages.index(WorkflowState.SUPERVISOR_READY) < stages.index(WorkflowState.PROPOSAL_GENERATION)


async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"readiness_run", "supervisor_brief"} <= set(names)


async def feasibility_accepted(repo):  # noqa: F811
    await plan_approved(repo)
    run = await repo.start_feasibility_run(WS)
    saved = await repo.complete_feasibility_run(run.id, report(), **LLM)
    return await repo.accept_feasibility(WS, saved.id)


async def test_the_brief_is_saved_and_confirmed(repo):  # noqa: F811
    with pytest.raises(ValueError):
        await repo.start_readiness_run("nope")
    feasibility = await feasibility_accepted(repo)
    run = await repo.start_readiness_run(WS)
    assert run.status == ReadinessRunStatus.RUNNING and run.feasibility_report_id == feasibility.id
    with pytest.raises(ReadinessRunAlreadyRunningError):
        await repo.start_readiness_run(WS)
    saved = await repo.complete_readiness_run(run.id, brief(), brief_id="b-1", **LLM)
    assert saved.id == "b-1" and saved.status == SupervisorBriefStatus.DRAFT and saved.brief.ready
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.SUPERVISOR_READINESS
    with pytest.raises(ReadinessError):
        await repo.start_readiness_run(WS)
    with pytest.raises(ReadinessError, match="not this project's"):
        await repo.confirm_supervisor_ready(WS, "nope")
    confirmed = await repo.confirm_supervisor_ready(WS, "b-1")
    assert confirmed.status == SupervisorBriefStatus.CONFIRMED and confirmed.confirmed_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.SUPERVISOR_READY
    with pytest.raises(ReadinessError):
        await repo.confirm_supervisor_ready(WS, "b-1")


async def test_preparing_needs_accepted_feasibility(repo):  # noqa: F811
    await plan_approved(repo)
    with pytest.raises(ReadinessError, match="after feasibility is accepted"):
        await repo.start_readiness_run(WS)


async def test_an_incomplete_brief_is_not_saved_and_runs_can_fail(repo):  # noqa: F811
    await feasibility_accepted(repo)
    run = await repo.start_readiness_run(WS)
    checks = brief().checks
    checks[0] = checks[1]
    with pytest.raises(SupervisorBriefRuleError):
        await repo.complete_readiness_run(run.id, brief(checks=checks), **LLM)
    failed = await repo.fail_readiness_run(run.id, "boom")
    assert failed.status == ReadinessRunStatus.FAILED
    retry = await repo.start_readiness_run(WS)
    await repo.complete_readiness_run(retry.id, brief(), **LLM)
