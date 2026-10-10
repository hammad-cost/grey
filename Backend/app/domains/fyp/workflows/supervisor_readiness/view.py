"""What the student sees about supervisor readiness (Release 0.13), built from the Project Brain."""
from pydantic import BaseModel

from app.core.brain.schemas import FeasibilityStatus, StoredSupervisorBrief, WorkspaceBrainSnapshot


class SupervisorBriefView(BaseModel):
    """Everything the supervisor readiness cards need, in one piece."""
    fyp_title: str
    brief: StoredSupervisorBrief | None = None
    ready: bool | None = None                     # every check passes (None until prepared)
    attention_count: int = 0


def build_supervisor_brief_view(snapshot: WorkspaceBrainSnapshot) -> SupervisorBriefView | None:
    """The supervisor brief view, or None until feasibility is accepted."""
    design, feasibility = snapshot.fyp_design, snapshot.feasibility_report
    if design is None or feasibility is None or feasibility.status != FeasibilityStatus.ACCEPTED:
        return None
    brief = snapshot.supervisor_brief
    return SupervisorBriefView(
        fyp_title=design.title,
        brief=brief,
        ready=brief.brief.ready if brief else None,
        attention_count=sum(1 for c in brief.brief.checks if c.status.value == "attention") if brief else 0,
    )
