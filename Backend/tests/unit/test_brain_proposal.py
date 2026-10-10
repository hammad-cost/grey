"""
Tests for proposal storage and rules in the Project Brain (Release 0.14, Step 1).
"""
import pytest
from sqlalchemy import inspect

from app.core.brain.proposal_rules import (
    MODEL_SECTIONS,
    ProposalRuleError,
    proposal_rule_broken,
    rewrite_problem,
)
from app.core.brain.repository import ProposalError, ProposalRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_PROPOSAL_REWRITES,
    Proposal,
    ProposalReference,
    ProposalRunStatus,
    ProposalSection,
    ProposalSectionId,
    ProposalStatus,
    WorkflowState,
    WrittenBy,
)
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, repo, session  # noqa: F401 (fixtures)
from tests.unit.test_brain_supervisor import brief, feasibility_accepted

REFERENCE = ProposalReference(number=1, title="Harbor report", organization="Harbor Systems",
                              url="https://harbor.example/report", source_type="government_report")


def proposal(text: str = "Operators review tracks by hand [1].") -> Proposal:
    return Proposal(
        title="Explainable alerts",
        sections=[
            ProposalSection(
                id=s, title=s.value.replace("_", " ").title(), paragraphs=[text], sources=["Approved FYP design"],
                written_by=WrittenBy.MODEL if s in MODEL_SECTIONS else WrittenBy.GREY,
            )
            for s in ProposalSectionId
        ],
        references=[REFERENCE],
    )


def test_a_complete_proposal_passes():
    assert proposal_rule_broken(proposal()) is None
    assert len(MODEL_SECTIONS) == 11


def test_proposal_rules():
    assert proposal_rule_broken(proposal("As shown in [2].")) == "unknown_citation"
    swapped = proposal()
    swapped.sections[0], swapped.sections[1] = swapped.sections[1], swapped.sections[0]
    assert proposal_rule_broken(swapped) == "wrong_sections"
    wrong = proposal()
    wrong.sections[0] = wrong.sections[0].model_copy(update={"written_by": WrittenBy.MODEL})
    assert proposal_rule_broken(wrong) == "wrong_author"


def test_only_model_sections_can_be_rewritten():
    assert rewrite_problem(ProposalSectionId.INTRODUCTION) is None
    assert "can't be rewritten" in rewrite_problem(ProposalSectionId.DATASET)


def test_the_journey_ends_at_complete():
    stages = list(WorkflowState)
    assert stages.index(WorkflowState.SUPERVISOR_READY) + 1 == stages.index(WorkflowState.PROPOSAL_GENERATION)
    assert stages[-1] == WorkflowState.COMPLETE


async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"proposal_run", "proposal"} <= set(names)


async def supervisor_ready(repo):  # noqa: F811
    await feasibility_accepted(repo)
    run = await repo.start_readiness_run(WS)
    saved = await repo.complete_readiness_run(run.id, brief(), **LLM)
    return await repo.confirm_supervisor_ready(WS, saved.id)


async def written(repo):  # noqa: F811
    await supervisor_ready(repo)
    run = await repo.start_proposal_run(WS)
    return await repo.complete_proposal_run(run.id, proposal(), **LLM)


async def test_the_proposal_is_saved_rewritten_and_finalized(repo):  # noqa: F811
    with pytest.raises(ValueError):
        await repo.start_proposal_run("nope")
    ready = await supervisor_ready(repo)
    run = await repo.start_proposal_run(WS)
    assert run.status == ProposalRunStatus.RUNNING and run.supervisor_brief_id == ready.id and run.section is None
    with pytest.raises(ProposalRunAlreadyRunningError):
        await repo.start_proposal_run(WS)
    saved = await repo.complete_proposal_run(run.id, proposal(), proposal_id="p-1", **LLM)
    assert saved.id == "p-1" and saved.status == ProposalStatus.DRAFT
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.PROPOSAL_GENERATION
    with pytest.raises(ProposalError):
        await repo.start_proposal_run(WS)

    with pytest.raises(ProposalError, match="can't be rewritten"):
        await repo.start_proposal_run(WS, ProposalSectionId.DATASET)
    for n in range(MAX_PROPOSAL_REWRITES):
        rewrite = await repo.start_proposal_run(WS, ProposalSectionId.INTRODUCTION)
        assert rewrite.section == ProposalSectionId.INTRODUCTION
        replaced = await repo.complete_proposal_run(rewrite.id, proposal(), **LLM)
        assert replaced.id == "p-1" and replaced.rewrites_used == n + 1
    with pytest.raises(ProposalError, match="rewrites have been used"):
        await repo.start_proposal_run(WS, ProposalSectionId.INTRODUCTION)

    with pytest.raises(ProposalError, match="not this project's"):
        await repo.finalize_proposal(WS, "nope")
    final = await repo.finalize_proposal(WS, "p-1")
    assert final.status == ProposalStatus.FINAL and final.finalized_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.COMPLETE
    with pytest.raises(ProposalError):
        await repo.finalize_proposal(WS, "p-1")


async def test_writing_needs_a_confirmed_supervisor_brief(repo):  # noqa: F811
    await feasibility_accepted(repo)
    with pytest.raises(ProposalError, match="ready for your supervisor"):
        await repo.start_proposal_run(WS)


async def test_a_proposal_breaking_the_rules_is_not_saved_and_runs_can_fail(repo):  # noqa: F811
    await supervisor_ready(repo)
    run = await repo.start_proposal_run(WS)
    with pytest.raises(ProposalRuleError):
        await repo.complete_proposal_run(run.id, proposal("See [7]."), **LLM)
    failed = await repo.fail_proposal_run(run.id, "boom")
    assert failed.status == ProposalRunStatus.FAILED
    retry = await repo.start_proposal_run(WS)
    await repo.complete_proposal_run(retry.id, proposal(), **LLM)
