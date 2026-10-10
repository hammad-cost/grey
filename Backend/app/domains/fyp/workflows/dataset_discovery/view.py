"""
What the student sees about dataset discovery (Release 0.8), built from the Project Brain.

Which re-searches are offered is decided here, by the same rules the Brain
uses, so the frontend never has to guess (e.g. "I'd rather create or collect
my own data" is not offered when the primary already is the student's own data).
"""
from pydantic import BaseModel

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.dataset_rules import research_problem
from app.core.brain.schemas import (
    MAX_DATASET_RESEARCHES,
    AIStrategyStatus,
    DatasetPlanStatus,
    DatasetPreference,
    StoredDatasetPlan,
    WorkspaceBrainSnapshot,
)


class DatasetView(BaseModel):
    """Everything the dataset cards need, in one piece."""
    fyp_title: str
    uses_ai: bool                                  # from the approved AI strategy
    ai_task: str | None = None                     # e.g. "anomaly_detection", None without AI
    plan: StoredDatasetPlan | None = None
    searches_used: int = 0                         # in the search that produced the current plan
    pages_found: int = 0                           # dataset pages that search found
    researches_left: int = MAX_DATASET_RESEARCHES
    max_researches: int = MAX_DATASET_RESEARCHES
    available_researches: list[DatasetPreference] = []   # what the student may ask for right now


def _available_researches(plan: StoredDatasetPlan | None) -> list[DatasetPreference]:
    if plan is None or plan.status != DatasetPlanStatus.DRAFT:
        return []
    if plan.researches_used >= MAX_DATASET_RESEARCHES:
        return []
    return [p for p in DatasetPreference if research_problem(plan.plan, p) is None]


def build_dataset_view(snapshot: WorkspaceBrainSnapshot) -> DatasetView | None:
    """The dataset view for a project, or None until the AI strategy is approved."""
    design = snapshot.fyp_design
    strategy = snapshot.ai_strategy
    if design is None or strategy is None or strategy.status != AIStrategyStatus.APPROVED:
        return None
    plan = snapshot.dataset_plan
    run = snapshot.dataset_run
    current_run = run is not None and plan is not None and run.id == plan.run_id
    return DatasetView(
        fyp_title=design.title,
        uses_ai=uses_ai(strategy.strategy.necessity),
        ai_task=strategy.strategy.task_type.value if strategy.strategy.task_type else None,
        plan=plan,
        searches_used=run.searches_used if current_run else 0,
        pages_found=run.candidates_found if current_run else 0,
        researches_left=max(0, MAX_DATASET_RESEARCHES - plan.researches_used) if plan else MAX_DATASET_RESEARCHES,
        available_researches=_available_researches(plan),
    )
