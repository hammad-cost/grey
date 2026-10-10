"""
LangGraph state for the Technical Plan workflow (Release 0.11: architecture + evaluation).
Execution state only — the runner rebuilds it from the Project Brain when needed.
"""
from typing import TypedDict


class TechnicalPlanState(TypedDict, total=False):
    """
    The approved decisions the skill needs (plain JSON data), plus:
    plan / plan_id     — the current TechnicalPlan and its id (the Brain uses the same id).
    plan_output        — the design_architecture skill's full result, until the runner saves it.
    redesigns_used     — how many redesigns have been saved.
    preference         — the ArchitecturePreference value for the redesign being run, else None.
    approved_plan_id   — set when the student approves; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    problem: dict
    design: dict
    definition: dict
    strategy: dict
    dataset: dict
    models: dict
    technology: dict
    plan: dict | None
    plan_id: str | None
    plan_output: dict | None
    redesigns_used: int
    preference: str | None
    approved_plan_id: str | None
