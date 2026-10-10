"""
Dataset Discovery workflow nodes (Release 0.8).

Rules (same as the other workflows):
  - Nodes never touch the database — the runner saves results to the Brain.
  - Skills are looked up by name in the Skill Registry, never created here.
  - Nodes forward only safe progress (step labels), never model reasoning.
  - The student's selection is a mandatory HITL interrupt.
"""
import uuid

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from app.core.brain.dataset_rules import research_problem
from app.core.brain.schemas import (
    MAX_DATASET_RESEARCHES,
    AIStrategy,
    DatasetCandidate,
    DatasetChoice,
    DatasetPlan,
    DatasetPreference,
    FunctionalArea,
    ProjectDefinition,
    WorkflowState,
)
from app.core.skills.registry import SkillRegistry
from app.domains.fyp.skills.find_datasets import DatasetProgress, FindDatasetsInput
from app.domains.fyp.skills.fyp_design_shared import ProblemBrief
from app.domains.fyp.workflows.dataset_discovery.state import DatasetDiscoveryState

# Name the skill is registered under in the Skill Registry.
FIND_DATASETS_SKILL_NAME = "find_datasets"

# Marks a progress update on LangGraph's custom stream.
DATASET_PROGRESS_KIND = "dataset_progress"

SELECT = "select"
RESEARCH = "research"


def _forwarder():
    write = get_stream_writer()

    async def forward(progress: DatasetProgress) -> None:
        write({"kind": DATASET_PROGRESS_KIND, "progress": progress.model_dump(mode="json")})

    return forward


def make_find_datasets_node(skills: SkillRegistry):
    """
    Build the find_datasets node: search dataset sites and recommend a primary
    dataset and an alternative (blueprint §24–25). On a re-search the skill also
    gets the student's preference, the previous recommendation and the pages
    found before. The recommendation keeps one id; the runner saves it with that id.
    """

    async def find_datasets_node(state: DatasetDiscoveryState) -> dict:
        preference = state.get("preference")
        previous = state.get("plan")
        output = await skills.get(FIND_DATASETS_SKILL_NAME).execute(
            FindDatasetsInput(
                workspace_id=state["workspace_id"],
                industry=state["industry"],
                branch=state["branch"],
                area=FunctionalArea.model_validate(state["area"]),
                problem=ProblemBrief.model_validate(state["problem"]),
                definition=ProjectDefinition.model_validate(state["definition"]),
                strategy=AIStrategy.model_validate(state["strategy"]),
                preference=DatasetPreference(preference) if preference else None,
                previous_plan=DatasetPlan.model_validate(previous) if preference and previous else None,
                known_candidates=[
                    DatasetCandidate.model_validate(c) for c in state.get("known_candidates", [])
                ] if preference else [],
            ),
            on_progress=_forwarder(),
        )
        return {
            "plan_output": output.model_dump(mode="json"),
            "plan": output.plan.model_dump(mode="json"),
            "plan_id": state.get("plan_id") or str(uuid.uuid4()),
            "known_candidates": [c.model_dump(mode="json") for c in output.candidates],
            "researches_used": state.get("researches_used", 0) + (1 if preference else 0),
            "preference": None,
            "workflow_state": WorkflowState.DATASET_DISCOVERY.value,
        }

    return find_datasets_node


def dataset_review_node(state: DatasetDiscoveryState) -> dict:
    """
    Pause until the student selects one of the two datasets or asks Grey to
    search again with a preference (mandatory HITL). The API resumes the graph with
    Command(resume={"action": "select", "plan_id": …, "choice": "primary" | "alternative"}) or
    Command(resume={"action": "research", "preference": "other_options" | "own_data"}).
    A re-search goes back to find_datasets; a selection ends the workflow.
    """
    used = state.get("researches_used", 0)
    decision = interrupt({
        "stage": WorkflowState.DATASET_DISCOVERY.value,
        "plan_id": state.get("plan_id"),
        "researches_left": max(0, MAX_DATASET_RESEARCHES - used),
        "prompt": "Select the primary or the alternative dataset, or ask Grey to search again.",
    })

    action = decision.get("action") if isinstance(decision, dict) else None
    if action == SELECT:
        if decision.get("plan_id") != state.get("plan_id"):
            raise ValueError("Only this project's datasets can be selected.")
        return {
            "selected_choice": DatasetChoice(decision.get("choice")).value,
            "workflow_state": WorkflowState.DATASET_SELECTED.value,
        }
    if action == RESEARCH:
        if used >= MAX_DATASET_RESEARCHES:
            raise ValueError(f"All {MAX_DATASET_RESEARCHES} new searches have been used.")
        preference = DatasetPreference(decision.get("preference"))
        problem = research_problem(DatasetPlan.model_validate(state["plan"]), preference)
        if problem is not None:
            raise ValueError(problem)
        return {"preference": preference.value}
    raise ValueError(f"Unknown dataset review action: {action!r}.")


def after_review(state: DatasetDiscoveryState) -> str:
    """Selected → the workflow ends. Otherwise (a re-search) → back to find_datasets."""
    return "selected" if state.get("selected_choice") else "research"
