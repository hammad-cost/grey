"""
LangGraph state for the Feasibility workflow (Release 0.12).
Execution state only — the runner rebuilds it from the Project Brain when needed.
"""
from typing import TypedDict


class FeasibilityState(TypedDict, total=False):
    """
    The approved decisions the skill needs (plain JSON data), plus:
    report / report_id  — the FeasibilityReport and its id (the Brain uses the same id).
    report_output       — the assess_feasibility skill's full result, until the runner saves it.
    accepted_report_id  — set when the student accepts; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    problem: dict
    evidence_tiers: list[str]
    design: dict
    definition: dict
    strategy: dict
    dataset: dict
    models: dict
    technology: dict
    technical: dict
    report: dict | None
    report_id: str | None
    report_output: dict | None
    accepted_report_id: str | None
