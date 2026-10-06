"""
LangGraph state for the FYP Design workflow (Release 0.5).

Execution state only — NOT the Project Brain. The runner rebuilds it from the
Brain whenever needed (after a restart, a retry or a failed redesign), so the
Brain stays the single source of truth.
"""
from typing import TypedDict


class FYPDesignState(TypedDict, total=False):
    """
    workspace_id      — links this execution back to the Project Brain.
    workflow_state    — mirrors the WorkflowState value (string form).
    industry, branch  — the student's earlier decisions.
    problem           — the chosen problem as a ProblemBrief (plain JSON data).
    area              — the FunctionalArea, once classified (plain JSON data).
    area_output       — the classify_area skill's full result, until the runner saves it.
    design            — the current FYPDesign draft (plain JSON data).
    design_output     — the design_fyp skill's full result, until the runner saves it.
    design_id         — the id given to the current draft; the Brain uses the same id.
    adjustments_used  — redesigns used so far (at most MAX_FYP_ADJUSTMENTS).
    adjustment        — the redesign the student just asked for: {"adjustment", "note"}.
    approved_design_id — set when the student approves; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    problem: dict
    area: dict | None
    area_output: dict | None
    design: dict | None
    design_output: dict | None
    design_id: str | None
    adjustments_used: int
    adjustment: dict | None
    approved_design_id: str | None
