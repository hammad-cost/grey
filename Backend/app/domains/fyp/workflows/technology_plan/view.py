"""What the student sees about the technology plan (Release 0.10), built from the Project Brain."""
from pydantic import BaseModel

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import (
    MAX_TECHNOLOGY_REPLANS,
    ModelPlanStatus,
    StoredTechnologyPlan,
    TechnologyPlanStatus,
    WorkspaceBrainSnapshot,
)


class TechnologyView(BaseModel):
    """Everything the technology cards need, in one piece."""
    fyp_title: str
    uses_ai: bool
    plan: StoredTechnologyPlan | None = None
    replans_left: int = MAX_TECHNOLOGY_REPLANS
    max_replans: int = MAX_TECHNOLOGY_REPLANS
    can_replan: bool = False


def build_technology_view(snapshot: WorkspaceBrainSnapshot) -> TechnologyView | None:
    """The technology view, or None until the model plan is approved."""
    design, strategy, models = snapshot.fyp_design, snapshot.ai_strategy, snapshot.model_plan
    if design is None or strategy is None or models is None or models.status != ModelPlanStatus.APPROVED:
        return None
    plan = snapshot.technology_plan
    left = max(0, MAX_TECHNOLOGY_REPLANS - plan.replans_used) if plan else MAX_TECHNOLOGY_REPLANS
    return TechnologyView(
        fyp_title=design.title,
        uses_ai=uses_ai(strategy.strategy.necessity),
        plan=plan,
        replans_left=left,
        can_replan=plan is not None and plan.status == TechnologyPlanStatus.DRAFT and left > 0,
    )
