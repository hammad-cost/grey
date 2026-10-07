"""
LangGraph state for the Project Definition workflow (Release 0.6).

Execution state only — NOT the Project Brain. The runner rebuilds it from the
Brain whenever needed (after a restart or a retry), so the Brain stays the
single source of truth.
"""
from typing import TypedDict


class ProjectDefinitionState(TypedDict, total=False):
    """
    workspace_id           — links this execution back to the Project Brain.
    workflow_state         — mirrors the WorkflowState value (string form).
    industry, branch       — the student's earlier decisions.
    area                   — the FunctionalArea (plain JSON data).
    problem                — the chosen problem as a ProblemBrief (plain JSON data).
    design                 — the approved FYPDesign (plain JSON data).
    definition_output      — the define_project skill's full result, until the runner saves it.
    definition_id          — the id given to the definition; the Brain uses the same id.
    scope                  — the scope items with their ids, kinds and positions
                             (StoredScopeItem as plain JSON data), kept in step with the Brain.
    approved_definition_id — set when the student approves the scope; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    industry: str
    branch: str
    area: dict
    problem: dict
    design: dict
    definition_output: dict | None
    definition_id: str | None
    scope: list[dict]
    approved_definition_id: str | None
