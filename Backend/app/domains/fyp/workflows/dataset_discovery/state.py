"""
LangGraph state for the Dataset Discovery workflow (Release 0.8).

Execution state only — NOT the Project Brain. The runner rebuilds it from the
Brain whenever needed (after a restart or a retry), so the Brain stays the
single source of truth.
"""
from typing import TypedDict


class DatasetDiscoveryState(TypedDict, total=False):
    """
    workspace_id         — links this execution back to the Project Brain.
    workflow_state       — mirrors the WorkflowState value (string form).
    industry, branch     — the student's earlier decisions.
    area                 — the FunctionalArea (plain JSON data).
    problem              — the chosen problem as a ProblemBrief (plain JSON data).
    definition           — the approved ProjectDefinition with its scope (plain JSON data).
    strategy             — the approved AIStrategy (plain JSON data).
    plan                 — the current DatasetPlan (plain JSON data), None before the first search.
    plan_id              — the id given to the recommendation; the Brain uses the same id.
    plan_output          — the find_datasets skill's full result, until the runner saves it.
    known_candidates     — the pages the latest search found (a re-search may reuse them).
    researches_used      — how many re-searches have been saved (kept in step with the Brain).
    preference           — the DatasetPreference value for the re-search being run, else None.
    selected_choice      — "primary" or "alternative" once the student selects; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    area: dict
    problem: dict
    definition: dict
    strategy: dict
    plan: dict | None
    plan_id: str | None
    plan_output: dict | None
    known_candidates: list[dict]
    researches_used: int
    preference: str | None
    selected_choice: str | None
