"""What the student sees about the architecture and evaluation plan (Release 0.11), built from the Project Brain."""
from pydantic import BaseModel

from app.core.brain.ai_strategy_rules import uses_ai
from app.core.brain.schemas import (
    MAX_ARCHITECTURE_REDESIGNS,
    StoredTechnicalPlan,
    TechnicalPlanStatus,
    TechnologyPlanStatus,
    WorkspaceBrainSnapshot,
)


class TechnicalPlanView(BaseModel):
    """Everything the architecture cards need, in one piece."""
    fyp_title: str
    uses_ai: bool
    ai_task: str | None = None
    plan: StoredTechnicalPlan | None = None
    redesigns_left: int = MAX_ARCHITECTURE_REDESIGNS
    max_redesigns: int = MAX_ARCHITECTURE_REDESIGNS
    can_redesign: bool = False


def build_technical_plan_view(snapshot: WorkspaceBrainSnapshot) -> TechnicalPlanView | None:
    """The technical plan view, or None until the technology plan is approved."""
    design, strategy, technology = snapshot.fyp_design, snapshot.ai_strategy, snapshot.technology_plan
    if design is None or strategy is None or technology is None or technology.status != TechnologyPlanStatus.APPROVED:
        return None
    plan = snapshot.technical_plan
    left = max(0, MAX_ARCHITECTURE_REDESIGNS - plan.redesigns_used) if plan else MAX_ARCHITECTURE_REDESIGNS
    return TechnicalPlanView(
        fyp_title=design.title,
        uses_ai=uses_ai(strategy.strategy.necessity),
        ai_task=strategy.strategy.task_type.value if strategy.strategy.task_type else None,
        plan=plan,
        redesigns_left=left,
        can_redesign=plan is not None and plan.status == TechnicalPlanStatus.DRAFT and left > 0,
    )
