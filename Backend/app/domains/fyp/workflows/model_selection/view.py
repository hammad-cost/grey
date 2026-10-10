"""
What the student sees about pretrained models and APIs (Release 0.9), built from the Project Brain.
Which re-searches are offered is decided here, by the same rules the Brain uses.
"""
from pydantic import BaseModel

from app.core.brain.model_rules import research_problem
from app.core.brain.schemas import (
    MAX_MODEL_RESEARCHES,
    DatasetPlanStatus,
    ModelPlanStatus,
    ModelPreference,
    StoredModelPlan,
    WorkspaceBrainSnapshot,
)


class ModelView(BaseModel):
    """Everything the model cards need, in one piece."""
    fyp_title: str
    ai_task: str | None = None                     # from the approved AI strategy
    primary_approach: str | None = None            # e.g. "train_model"
    dataset_name: str                              # the selected dataset
    plan: StoredModelPlan | None = None
    searches_used: int = 0
    pages_found: int = 0
    researches_left: int = MAX_MODEL_RESEARCHES
    max_researches: int = MAX_MODEL_RESEARCHES
    available_researches: list[ModelPreference] = []


def _available_researches(plan: StoredModelPlan | None) -> list[ModelPreference]:
    if plan is None or plan.status != ModelPlanStatus.DRAFT or plan.researches_used >= MAX_MODEL_RESEARCHES:
        return []
    return [p for p in ModelPreference if research_problem(plan.plan, p) is None]


def build_model_view(snapshot: WorkspaceBrainSnapshot) -> ModelView | None:
    """The model view for a project, or None until a dataset is selected."""
    design, strategy, dataset = snapshot.fyp_design, snapshot.ai_strategy, snapshot.dataset_plan
    if design is None or strategy is None or dataset is None or dataset.status != DatasetPlanStatus.SELECTED:
        return None
    plan, run = snapshot.model_plan, snapshot.model_run
    current_run = run is not None and plan is not None and run.id == plan.run_id
    primary = strategy.strategy.primary_strategy
    return ModelView(
        fyp_title=design.title,
        ai_task=strategy.strategy.task_type.value if strategy.strategy.task_type else None,
        primary_approach=primary.approach.value if primary else None,
        dataset_name=dataset.selected_option.name,
        plan=plan,
        searches_used=run.searches_used if current_run else 0,
        pages_found=run.candidates_found if current_run else 0,
        researches_left=max(0, MAX_MODEL_RESEARCHES - plan.researches_used) if plan else MAX_MODEL_RESEARCHES,
        available_researches=_available_researches(plan),
    )
