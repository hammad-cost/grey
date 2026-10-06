"""
Shared pieces for the two Release 0.5 skills (classify_area and design_fyp).

  ProblemBrief       — the chosen problem as the skills see it. The runner builds
                       it from the Project Brain, so skills never touch the database.
  DesignPhase /
  DesignProgress     — safe progress updates ("Designing a student-sized FYP"),
                       never the model's reasoning.
  text checks        — plain-code rules both skills use to reject a reply:
                       links, organization names, and named technologies.
"""
import re
from collections.abc import Awaitable, Callable
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import ProblemTaskType, StoredProblemCandidate

MAX_BRIEF_TEXT = 300
MAX_EVIDENCE_POINTS = 5


class ProblemBrief(BaseModel):
    """The student's chosen problem, shortened, with the points its evidence supports."""
    title: str = Field(min_length=1)
    real_world_problem: str = Field(min_length=1)
    observed_solutions: str = Field(min_length=1)
    technical_problem: str = Field(min_length=1)
    task_type: ProblemTaskType
    why_it_matters: str = Field(min_length=1)
    possible_fyp_direction: str = Field(min_length=1)
    evidence_points: list[str] = []      # what the cited sources show, in their own words
    organizations: list[str] = []        # who is behind the cited sources (never put in a design)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_BRIEF_TEXT else text[: MAX_BRIEF_TEXT - 1].rstrip() + "…"


def brief_from_problem(problem: StoredProblemCandidate) -> ProblemBrief:
    """Build the skills' view of a stored problem (no URLs, ids or database details)."""
    return ProblemBrief(
        title=problem.title,
        real_world_problem=_short(problem.real_world_problem),
        observed_solutions=_short(problem.observed_solutions),
        technical_problem=_short(problem.technical_problem),
        task_type=problem.task_type,
        why_it_matters=_short(problem.why_it_matters),
        possible_fyp_direction=_short(problem.possible_fyp_direction),
        evidence_points=[_short(s.supporting_point) for s in problem.evidence[:MAX_EVIDENCE_POINTS]],
        organizations=sorted({s.organization for s in problem.evidence}),
    )


def brief_for_model(brief: ProblemBrief) -> dict:
    """What the model is shown about the problem (organizations are left out on purpose)."""
    return brief.model_dump(mode="json", exclude={"organizations"})


# ── Progress ──────────────────────────────────────────────────────────────────

class DesignPhase(str, Enum):
    """What Grey is doing while it turns the problem into an FYP. Safe activity only."""
    CLASSIFYING_AREA = "classifying_area"
    DESIGNING_FYP = "designing_fyp"
    CHECKING_DESIGN = "checking_design"


class DesignProgress(BaseModel):
    phase: DesignPhase
    label: str


ProgressCallback = Callable[[DesignProgress], Awaitable[None]]


# ── Text checks (plain code, no AI) ───────────────────────────────────────────

_URL = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|org|net|gov|edu|io|ai|example)\b", re.IGNORECASE)

# Named products, models, datasets and services. Release 0.5 designs WHAT the
# student builds; choosing a dataset, model, API or stack comes in later stages,
# so a design that names one is rejected. Only unambiguous names are listed.
SPECIFIC_TECHNOLOGIES = [
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn", "xgboost", "lightgbm",
    "hugging face", "huggingface", "bert", "gpt", "chatgpt", "openai", "llama", "gemini", "claude",
    "yolo", "resnet", "lstm", "opencv",
    "django", "flask", "fastapi", "node.js", "nodejs", "react.js", "reactjs", "next.js",
    "angular", "vue.js", "flutter", "firebase", "mongodb", "mysql", "postgresql",
    "aws", "azure", "google cloud",
    "kaggle", "imagenet", "mimic-iii", "mimic-iv", "physionet",
    "raspberry pi", "arduino",
]
_TECHNOLOGY = re.compile(
    r"(?<![\w.-])(" + "|".join(re.escape(name) for name in SPECIFIC_TECHNOLOGIES) + r")(?![\w-])",
    re.IGNORECASE,
)


def contains_url(text: str) -> bool:
    return bool(_URL.search(text))


def named_technology(text: str) -> str | None:
    """The first named technology in the text, or None."""
    match = _TECHNOLOGY.search(text)
    return match.group(1) if match else None


def names_organization(text: str, organizations: list[str]) -> bool:
    """True if one of the evidence's organizations is named (e.g. 'Northwind Analytics (sample startup)')."""
    lowered = text.lower()
    for organization in organizations:
        name = organization.split("(")[0].strip().lower()
        if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", lowered):
            return True
    return False
