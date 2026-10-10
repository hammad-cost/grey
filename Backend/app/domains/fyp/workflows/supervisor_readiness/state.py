"""
LangGraph state for the Supervisor Readiness workflow (Release 0.13).
Execution state only — the runner rebuilds it from the Project Brain when needed.
"""
from typing import TypedDict


class SupervisorReadinessState(TypedDict, total=False):
    """
    inputs              — the SupervisorBriefInput (every approved decision), as plain JSON data.
    brief / brief_id    — the SupervisorBrief and its id (the Brain uses the same id).
    brief_output        — the skill's full result, until the runner saves it.
    confirmed_brief_id  — set when the student confirms; the workflow then ends.
    """
    workspace_id: str
    workflow_state: str
    inputs: dict
    brief: dict | None
    brief_id: str | None
    brief_output: dict | None
    confirmed_brief_id: str | None
