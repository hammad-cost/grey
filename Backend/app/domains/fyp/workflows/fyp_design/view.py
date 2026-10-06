"""
What the student sees about their FYP (Release 0.5), built from the Project Brain.

"Why this FYP?" (blueprint §18) is assembled by plain code, never written by
the model in one go, so it can't invent evidence:
  - where the problem came from, why it matters and what organizations are
    doing → the chosen problem, whose every citation was checked against
    stored evidence when it was found (Release 0.3)
  - the organizations and sources → the stored evidence those citations point to
  - how Grey made it student-sized → the checked design's scope_reduction
"""
from pydantic import BaseModel

from app.core.brain.schemas import (
    MAX_FYP_ADJUSTMENTS,
    EvidenceStrength,
    ProblemSourceDetail,
    StoredFunctionalArea,
    StoredFYPDesign,
    StoredProblemCandidate,
    WorkspaceBrainSnapshot,
)


class WhyThisFYP(BaseModel):
    problem_title: str
    where_the_problem_came_from: str        # the real-world problem, from the evidence
    why_it_matters: str
    what_organizations_are_doing: str
    organizations: list[str]                # who is behind the cited sources
    evidence: list[ProblemSourceDetail]     # the cited sources, with links (strongest first)
    evidence_strength: EvidenceStrength
    how_grey_made_it_student_sized: str     # from the design


class FYPDesignView(BaseModel):
    """Everything the FYP cards need, in one piece."""
    problem_id: str
    problem_title: str
    area: StoredFunctionalArea | None = None
    design: StoredFYPDesign | None = None
    why_this_fyp: WhyThisFYP | None = None
    adjustments_used: int = 0
    adjustments_left: int = MAX_FYP_ADJUSTMENTS
    max_adjustments: int = MAX_FYP_ADJUSTMENTS


def build_why_this_fyp(problem: StoredProblemCandidate, design: StoredFYPDesign) -> WhyThisFYP:
    organizations: list[str] = []
    for source in problem.evidence:
        if source.organization not in organizations:
            organizations.append(source.organization)
    return WhyThisFYP(
        problem_title=problem.title,
        where_the_problem_came_from=problem.real_world_problem,
        why_it_matters=problem.why_it_matters,
        what_organizations_are_doing=problem.observed_solutions,
        organizations=organizations,
        evidence=problem.evidence,
        evidence_strength=problem.evidence_strength,
        how_grey_made_it_student_sized=design.scope_reduction,
    )


def build_fyp_view(snapshot: WorkspaceBrainSnapshot) -> FYPDesignView | None:
    """The FYP view for a project, or None until a problem has been chosen."""
    problem = snapshot.selected_problem
    if problem is None:
        return None
    design = snapshot.fyp_design
    used = snapshot.fyp_adjustments_used
    return FYPDesignView(
        problem_id=problem.id,
        problem_title=problem.title,
        area=snapshot.functional_area,
        design=design,
        why_this_fyp=build_why_this_fyp(problem, design) if design else None,
        adjustments_used=used,
        adjustments_left=max(0, MAX_FYP_ADJUSTMENTS - used),
    )
