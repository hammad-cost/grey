"""
What the student sees about their project definition (Release 0.6), built
from the Project Brain.

The target user, input and output are taken from the approved FYP design,
not written again by the model, so the definition can't drift from the FYP
the student approved.
"""
from pydantic import BaseModel

from app.core.brain.schemas import (
    MAX_CORE_FEATURES,
    MIN_CORE_FEATURES,
    FYPDesignStatus,
    StoredProjectDefinition,
    WorkspaceBrainSnapshot,
)


class ProjectDefinitionView(BaseModel):
    """Everything the definition and scope cards need, in one piece."""
    fyp_title: str
    target_user: str              # from the approved design
    system_input: str             # from the approved design
    system_output: str            # from the approved design
    definition: StoredProjectDefinition | None = None
    min_core_features: int = MIN_CORE_FEATURES
    max_core_features: int = MAX_CORE_FEATURES


def build_definition_view(snapshot: WorkspaceBrainSnapshot) -> ProjectDefinitionView | None:
    """The definition view for a project, or None until the FYP design is approved."""
    design = snapshot.fyp_design
    if design is None or design.status != FYPDesignStatus.APPROVED:
        return None
    return ProjectDefinitionView(
        fyp_title=design.title,
        target_user=design.target_user,
        system_input=design.system_input,
        system_output=design.system_output,
        definition=snapshot.project_definition,
    )
