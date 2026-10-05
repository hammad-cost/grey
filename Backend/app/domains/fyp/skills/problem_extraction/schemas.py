"""
Types for the Problem Extraction skill.

Two groups:
  LLM-facing   — LLMProblemDrafts: the shape the language model must return.
                 Drafts cite evidence by short refs ("E3"), never by database id,
                 and are NOT trusted until validation.py has checked them.
  Grey-facing  — ProblemExtractionInput / Output: what the workflow sends and
                 gets back. The output holds validated ProblemCandidate objects
                 (from the Project Brain schemas), ready for the runner to save.
"""
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import ProblemCandidate, ProblemTaskType


# ── Skill input / output ──────────────────────────────────────────────────────

class ProblemExtractionInput(BaseModel):
    """What the skill needs. The evidence itself is read through an EvidenceReader."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)


class ProblemExtractionOutput(BaseModel):
    """The skill's result. The runner saves it; the skill never does."""
    candidates: list[ProblemCandidate]          # 3–5, strongest first
    provider: str                               # which LLM answered (for the run record)
    model: str
    prompt_version: str
    candidates_generated: int                   # drafts the LLM returned, all attempts
    rejection_summary: dict[str, int]           # why drafts/citations were dropped


class ProblemPhase(str, Enum):
    """Safe, student-facing activity while problems are being found."""
    REVIEWING_EVIDENCE = "reviewing_evidence"
    IDENTIFYING_PROBLEMS = "identifying_problems"
    CHECKING_PROBLEMS = "checking_problems"


class ProblemProgress(BaseModel):
    """One progress update. Says what Grey is doing — never how the model reasons."""
    phase: ProblemPhase
    label: str


# ── LLM-facing (untrusted until validated) ────────────────────────────────────

class LLMEvidenceCitation(BaseModel):
    ref: str = Field(min_length=1)                  # e.g. "E3"
    supporting_point: str = Field(min_length=1)     # what that source shows, in its own words


class LLMProblemDraft(BaseModel):
    title: str = Field(min_length=1)
    real_world_problem: str = Field(min_length=1)
    observed_solutions: str = Field(min_length=1)
    technical_problem: str = Field(min_length=1)
    task_type: ProblemTaskType
    why_it_matters: str = Field(min_length=1)
    possible_fyp_direction: str = Field(min_length=1)
    evidence: list[LLMEvidenceCitation] = Field(min_length=1)


class LLMProblemDrafts(BaseModel):
    """The whole reply the model must return."""
    problems: list[LLMProblemDraft] = Field(min_length=1, max_length=10)
