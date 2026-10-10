"""
LangGraph state for the Technology Plan workflow (Release 0.10).
Execution state only — the runner rebuilds it from the Project Brain when needed.
"""
from typing import TypedDict


class TechnologyPlanState(TypedDict, total=False):
    """
    The approved decisions the skill needs (plain JSON data), plus:
    plan / plan_id     — the current TechnologyPlan and its id (the Brain uses the same id).
    plan_output        — the plan_technology skill's full result, until the runner saves it.
    replans_used       — how many re-plans have been saved.
    preference         — the TechnologyPreference value for the re-plan being run, else None.
    approved_plan_id   — set when the student approves; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    area: dict
    problem: dict
    design: dict
    definition: dict
    strategy: dict
    dataset: dict
    models: dict
    plan: dict | None
    plan_id: str | None
    plan_output: dict | None
    replans_used: int
    preference: str | None
    approved_plan_id: str | None
