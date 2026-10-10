"""What the student sees about the feasibility analysis (Release 0.12), built from the Project Brain."""
from pydantic import BaseModel

from app.core.brain.feasibility_rules import DIMENSION_NAMES
from app.core.brain.schemas import StoredFeasibilityReport, TechnicalPlanStatus, WorkspaceBrainSnapshot


class FeasibilityView(BaseModel):
    """Everything the feasibility cards need, in one piece."""
    fyp_title: str
    report: StoredFeasibilityReport | None = None
    dimension_names: dict[str, str]           # plain names for the 13 dimensions, in display order


def build_feasibility_view(snapshot: WorkspaceBrainSnapshot) -> FeasibilityView | None:
    """The feasibility view, or None until the technical plan is approved."""
    design, technical = snapshot.fyp_design, snapshot.technical_plan
    if design is None or technical is None or technical.status != TechnicalPlanStatus.APPROVED:
        return None
    return FeasibilityView(
        fyp_title=design.title,
        report=snapshot.feasibility_report,
        dimension_names={d.value: name for d, name in DIMENSION_NAMES.items()},
    )
