"""
LangGraph state for the Discovery workflow.

This TypedDict is the in-memory state that LangGraph carries through the graph.
It is NOT the persistent Project Brain — it is execution state only.

The Project Brain (WorkspaceBrainRepository) is the durable source of truth.
LangGraph state is rebuilt from the Brain when needed and discarded when done.
"""
from typing import TypedDict


class DiscoveryState(TypedDict, total=False):
    """
    Execution state for the FYP Discovery workflow.

    workspace_id    — links this execution back to the persistent Project Brain.
    workflow_state  — mirrors the WorkflowState enum value (string form).
    industry        — the industry the student has chosen (or None).
    branch          — the branch the student has chosen (or None).
    research_output — the Evidence Research skill's result, as plain JSON data,
                      until the research runner saves it to the Project Brain.
    problem_output  — the Problem Extraction skill's result, as plain JSON data,
                      until the problem runner saves it (Release 0.3).
    problem_candidate_ids — the ids given to those problem options; the same ids
                      are used in the Project Brain, so a selection can be checked.
    selected_problem_id — the option the student chose.
    """
    workspace_id: str
    workflow_state: str
    industry: str | None
    branch: str | None
    research_output: dict | None
    problem_output: dict | None
    problem_candidate_ids: list[str]
    selected_problem_id: str | None
