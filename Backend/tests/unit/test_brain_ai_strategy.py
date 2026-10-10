"""
Tests for AI necessity check and AI strategy storage in the Project Brain (Release 0.7, Step 1).

Covers the consistency rules (ai_strategy_rules.py), the check runs, saving
the first strategy, re-checks with a preference (and their limits), approval,
and that each step only works at the right stage.

Uses an in-memory SQLite database so no files are created on disk.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect

from app.core.brain.ai_strategy_rules import (
    AIStrategyRuleError,
    recheck_problem,
    strategy_rule_broken,
    uses_ai,
)
from app.core.brain.models import AIStrategyRunRecord
from app.core.brain.repository import AIStrategyError, AIStrategyRunAlreadyRunningError
from app.core.brain.schemas import (
    MAX_AI_STRATEGY_RECHECKS,
    AIApproach,
    AINecessity,
    AIStrategy,
    AIStrategyPreference,
    AIStrategyRunStatus,
    AIStrategyStatus,
    AITaskType,
    StrategyChoice,
    WorkflowState,
)
from tests.unit.test_brain_fyp_design import LLM
from tests.unit.test_brain_project_definition import WS, defined, repo, session  # noqa: F401 (fixtures)


def ml_strategy(**changes) -> AIStrategy:
    """Traditional ML: train an anomaly detector, with a hybrid fallback."""
    values = dict(
        necessity=AINecessity.TRADITIONAL_ML,
        necessity_reason="Unusual tracks are hard to describe with fixed rules.",
        without_ai="Fixed speed and route limits could flag some tracks, but miss new patterns.",
        ai_component="The track checker that scores how unusual each track is.",
        non_ai_components=["Report upload", "Alert list"],
        task_type=AITaskType.ANOMALY_DETECTION,
        primary_strategy=StrategyChoice(approach=AIApproach.TRAIN_MODEL, reason="Public track data is enough."),
        fallback_strategy=StrategyChoice(approach=AIApproach.HYBRID, reason="Rules plus a small model."),
    )
    values.update(changes)
    return AIStrategy(**values)


def rule_based_strategy() -> AIStrategy:
    return AIStrategy(
        necessity=AINecessity.RULE_BASED,
        necessity_reason="Clear limits describe the unusual tracks well.",
        without_ai="Speed and route rules flag the tracks.",
        non_ai_components=["Report upload", "Rule checker", "Alert list"],
    )


async def scope_approved(repo, workspace_id: str = WS):
    """A project whose scope is approved (stage SCOPE_APPROVED). Returns the definition."""
    definition = await defined(repo, workspace_id)
    return await repo.approve_project_definition(workspace_id, definition.id)


async def checked(repo, strategy: AIStrategy | None = None, workspace_id: str = WS):
    """A project with a draft AI strategy (stage AI_STRATEGY). Returns the stored strategy."""
    await scope_approved(repo, workspace_id)
    run = await repo.start_ai_strategy_run(workspace_id)
    return await repo.complete_ai_strategy_run(run.id, strategy or ml_strategy(), **LLM)


async def rechecked(repo, preference: AIStrategyPreference, strategy: AIStrategy, workspace_id: str = WS):
    run = await repo.start_ai_strategy_run(workspace_id, preference)
    return await repo.complete_ai_strategy_run(run.id, strategy, **LLM)


# ── Rules (plain code) ────────────────────────────────────────────────────────

def test_which_verdicts_use_ai():
    assert {n for n in AINecessity if uses_ai(n)} == {
        AINecessity.AI_NECESSARY, AINecessity.AI_OPTIONAL, AINecessity.TRADITIONAL_ML, AINecessity.EXISTING_MODEL,
    }


def test_consistent_strategies_pass():
    assert strategy_rule_broken(ml_strategy()) is None
    assert strategy_rule_broken(ml_strategy(fallback_strategy=None)) is None
    assert strategy_rule_broken(rule_based_strategy()) is None


@pytest.mark.parametrize("strategy, rule", [
    (ml_strategy(ai_component=None), "missing_ai_details"),
    (ml_strategy(task_type=None), "missing_ai_details"),
    (ml_strategy(primary_strategy=None, fallback_strategy=None), "missing_ai_details"),
    (rule_based_strategy().model_copy(update={"task_type": AITaskType.CLASSIFICATION}), "ai_details_without_ai"),
    (rule_based_strategy().model_copy(update={"ai_component": "A model"}), "ai_details_without_ai"),
    (ml_strategy(primary_strategy=StrategyChoice(approach=AIApproach.USE_API, reason="r"),
                 fallback_strategy=None), "approach_mismatch"),
    (ml_strategy(task_type=AITaskType.GENERATIVE_AI), "approach_mismatch"),
    (ml_strategy(necessity=AINecessity.EXISTING_MODEL), "approach_mismatch"),     # existing model, but trains one
    (ml_strategy(fallback_strategy=StrategyChoice(approach=AIApproach.TRAIN_MODEL, reason="r")), "same_fallback"),
])
def test_inconsistent_strategies_are_caught(strategy, rule):
    assert strategy_rule_broken(strategy) == rule


def test_recheck_rules():
    ml = ml_strategy()
    ready_made = ml_strategy(
        necessity=AINecessity.EXISTING_MODEL,
        primary_strategy=StrategyChoice(approach=AIApproach.PRETRAINED_MODEL, reason="r"),
        fallback_strategy=None,
    )
    assert recheck_problem(ml, AIStrategyPreference.WITHOUT_AI) is None
    assert recheck_problem(ml, AIStrategyPreference.EXISTING_MODEL) is None
    assert "already uses a ready-made" in recheck_problem(ready_made, AIStrategyPreference.EXISTING_MODEL)
    assert "already works without AI" in recheck_problem(rule_based_strategy(), AIStrategyPreference.WITHOUT_AI)
    assert recheck_problem(rule_based_strategy(), AIStrategyPreference.EXISTING_MODEL) is not None


# ── Tables ────────────────────────────────────────────────────────────────────

async def test_new_tables_exist(session):  # noqa: F811
    names = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert {"ai_strategy_run", "ai_strategy"} <= set(names)


# ── First check ───────────────────────────────────────────────────────────────

async def test_the_first_check_saves_a_draft_and_moves_to_review(repo):  # noqa: F811
    definition = await scope_approved(repo)
    run = await repo.start_ai_strategy_run(WS)
    assert run.status == AIStrategyRunStatus.RUNNING
    assert run.preference is None

    stored = await repo.complete_ai_strategy_run(run.id, ml_strategy(), strategy_id="ai-1", **LLM)

    assert stored.id == "ai-1"
    assert stored.status == AIStrategyStatus.DRAFT
    assert stored.definition_id == definition.id
    assert stored.strategy.task_type == AITaskType.ANOMALY_DETECTION
    assert stored.rechecks_used == 0

    snapshot = await repo.get_snapshot(WS)
    assert snapshot.workflow_state == WorkflowState.AI_STRATEGY
    assert snapshot.ai_strategy.id == "ai-1"
    assert snapshot.ai_strategy_run.status == AIStrategyRunStatus.COMPLETE
    assert snapshot.ai_strategy_run.provider == LLM["provider"]


async def test_a_project_without_ai_is_stored_as_it_is(repo):  # noqa: F811
    stored = await checked(repo, rule_based_strategy())
    assert stored.strategy.necessity == AINecessity.RULE_BASED
    assert stored.strategy.task_type is None and stored.strategy.primary_strategy is None


async def test_the_check_needs_an_approved_scope(repo):  # noqa: F811
    await defined(repo)                                   # stage SCOPE, not approved yet
    with pytest.raises(AIStrategyError):
        await repo.start_ai_strategy_run(WS)
    with pytest.raises(ValueError):
        await repo.start_ai_strategy_run("nope")


async def test_the_first_check_happens_once(repo):  # noqa: F811
    await checked(repo)
    with pytest.raises(AIStrategyError):
        await repo.start_ai_strategy_run(WS)


async def test_an_inconsistent_strategy_is_never_saved(repo):  # noqa: F811
    await scope_approved(repo)
    run = await repo.start_ai_strategy_run(WS)
    with pytest.raises(AIStrategyRuleError):
        await repo.complete_ai_strategy_run(run.id, ml_strategy(task_type=None), **LLM)
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.SCOPE_APPROVED


async def test_only_one_check_at_a_time_but_stale_runs_are_replaced(repo, session):  # noqa: F811
    await scope_approved(repo)
    first = await repo.start_ai_strategy_run(WS)
    with pytest.raises(AIStrategyRunAlreadyRunningError):
        await repo.start_ai_strategy_run(WS)

    record = await session.get(AIStrategyRunRecord, first.id)
    record.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    await session.commit()

    second = await repo.start_ai_strategy_run(WS)
    assert second.id != first.id
    assert (await session.get(AIStrategyRunRecord, first.id)).status == AIStrategyRunStatus.FAILED.value


async def test_a_failed_check_can_be_retried(repo):  # noqa: F811
    await scope_approved(repo)
    run = await repo.start_ai_strategy_run(WS)
    failed = await repo.fail_ai_strategy_run(run.id, "LLMUnavailable: down")
    assert failed.status == AIStrategyRunStatus.FAILED
    assert failed.error == "LLMUnavailable: down"

    retry = await repo.start_ai_strategy_run(WS)
    await repo.complete_ai_strategy_run(retry.id, ml_strategy(), **LLM)
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.AI_STRATEGY


# ── Re-checks ─────────────────────────────────────────────────────────────────

async def test_a_recheck_replaces_the_draft_and_uses_one_up(repo):  # noqa: F811
    first = await checked(repo)

    stored = await rechecked(repo, AIStrategyPreference.WITHOUT_AI, rule_based_strategy())

    assert stored.id == first.id                          # the same strategy, new content
    assert stored.strategy.necessity == AINecessity.RULE_BASED
    assert stored.rechecks_used == 1
    assert stored.preference == AIStrategyPreference.WITHOUT_AI
    run = await repo.get_latest_ai_strategy_run(WS)
    assert run.preference == AIStrategyPreference.WITHOUT_AI
    assert stored.run_id == run.id
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.AI_STRATEGY


async def test_a_recheck_that_makes_no_sense_is_refused(repo):  # noqa: F811
    await checked(repo, rule_based_strategy())
    with pytest.raises(AIStrategyError, match="already works without AI"):
        await repo.start_ai_strategy_run(WS, AIStrategyPreference.WITHOUT_AI)


async def test_rechecks_are_limited(repo):  # noqa: F811
    await checked(repo)
    for _ in range(MAX_AI_STRATEGY_RECHECKS):
        await rechecked(repo, AIStrategyPreference.EXISTING_MODEL, ml_strategy())   # still trains a model

    with pytest.raises(AIStrategyError, match="re-checks have been used"):
        await repo.start_ai_strategy_run(WS, AIStrategyPreference.WITHOUT_AI)
    assert (await repo.get_ai_strategy(WS)).rechecks_used == MAX_AI_STRATEGY_RECHECKS


async def test_a_failed_recheck_does_not_use_one_up(repo):  # noqa: F811
    await checked(repo)
    run = await repo.start_ai_strategy_run(WS, AIStrategyPreference.WITHOUT_AI)
    await repo.fail_ai_strategy_run(run.id, "boom")
    assert (await repo.get_ai_strategy(WS)).rechecks_used == 0


async def test_a_recheck_needs_a_draft(repo):  # noqa: F811
    await scope_approved(repo)
    with pytest.raises(AIStrategyError):
        await repo.start_ai_strategy_run(WS, AIStrategyPreference.WITHOUT_AI)


# ── Approval ──────────────────────────────────────────────────────────────────

async def test_approval_ends_release_0_7(repo):  # noqa: F811
    stored = await checked(repo)

    approved = await repo.approve_ai_strategy(WS, stored.id)

    assert approved.status == AIStrategyStatus.APPROVED
    assert approved.approved_at is not None
    assert (await repo.get_snapshot(WS)).workflow_state == WorkflowState.AI_STRATEGY_APPROVED


async def test_approval_checks_the_id_and_the_stage(repo):  # noqa: F811
    stored = await checked(repo)
    with pytest.raises(AIStrategyError):
        await repo.approve_ai_strategy(WS, "someone-elses")

    await repo.approve_ai_strategy(WS, stored.id)
    with pytest.raises(AIStrategyError):
        await repo.approve_ai_strategy(WS, stored.id)               # already approved
    with pytest.raises(AIStrategyError):
        await repo.start_ai_strategy_run(WS, AIStrategyPreference.WITHOUT_AI)
