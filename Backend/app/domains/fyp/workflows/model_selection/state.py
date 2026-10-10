"""
LangGraph state for the Model Selection workflow (Release 0.9).

Execution state only — NOT the Project Brain. The runner rebuilds it from the
Brain whenever needed, so the Brain stays the single source of truth.
"""
from typing import TypedDict


class ModelSelectionState(TypedDict, total=False):
    """
    workspace_id, workflow_state, industry, branch — as in the other workflows.
    area, problem, definition, strategy — earlier approved decisions (plain JSON data).
    dataset            — the selected DatasetOption (plain JSON data).
    plan / plan_id     — the current ModelPlan and its id (the Brain uses the same id).
    plan_output        — the find_models skill's full result, until the runner saves it.
    known_candidates   — the pages the latest search found.
    researches_used    — how many re-searches have been saved.
    preference         — the ModelPreference value for the re-search being run, else None.
    approved_plan_id   — set when the student approves; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    area: dict
    problem: dict
    definition: dict
    strategy: dict
    dataset: dict
    plan: dict | None
    plan_id: str | None
    plan_output: dict | None
    known_candidates: list[dict]
    researches_used: int
    preference: str | None
    approved_plan_id: str | None
