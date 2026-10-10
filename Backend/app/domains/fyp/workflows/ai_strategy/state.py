"""
LangGraph state for the AI Strategy workflow (Release 0.7).

Execution state only — NOT the Project Brain. The runner rebuilds it from the
Brain whenever needed (after a restart or a retry), so the Brain stays the
single source of truth.
"""
from typing import TypedDict


class AIStrategyState(TypedDict, total=False):
    """
    workspace_id         — links this execution back to the Project Brain.
    workflow_state       — mirrors the WorkflowState value (string form).
    industry, branch     — the student's earlier decisions.
    area                 — the FunctionalArea (plain JSON data).
    problem              — the chosen problem as a ProblemBrief (plain JSON data).
    design               — the approved FYPDesign (plain JSON data).
    definition           — the approved ProjectDefinition with its scope (plain JSON data).
    strategy             — the current AIStrategy (plain JSON data), None before the first check.
    strategy_id          — the id given to the strategy; the Brain uses the same id.
    strategy_output      — the plan_ai_strategy skill's full result, until the runner saves it.
    rechecks_used        — how many re-checks have been saved (kept in step with the Brain).
    preference           — the AIStrategyPreference value for the re-check being run, else None.
    approved_strategy_id — set when the student approves; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    area: dict
    problem: dict
    design: dict
    definition: dict
    strategy: dict | None
    strategy_id: str | None
    strategy_output: dict | None
    rechecks_used: int
    preference: str | None
    approved_strategy_id: str | None
