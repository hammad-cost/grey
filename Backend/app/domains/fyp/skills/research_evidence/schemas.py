"""
Input, output and progress types for the Evidence Research skill.

The evidence itself uses the Project Brain type (EvidenceSource), so what the
skill returns can be saved by the repository without any conversion.
"""
from enum import Enum

from pydantic import BaseModel, Field

from app.core.brain.schemas import EvidenceSource, EvidenceTier, ResearchCategory


class ResearchEvidenceInput(BaseModel):
    """What the skill needs to know. Nothing else from the Brain is loaded."""
    workspace_id: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    max_sources_per_category: int = Field(default=5, ge=1, le=10)


class ResearchPhase(str, Enum):
    """
    The skill's part of the research timeline.

    research_started, storing_evidence and research_completed happen outside
    the skill (the workflow and repository do those), so they are not here.
    """
    SEARCHING_SOURCES = "searching_sources"
    SOURCES_FOUND = "sources_found"
    EVALUATING_EVIDENCE = "evaluating_evidence"


class ResearchProgress(BaseModel):
    """
    One safe, student-facing activity update.

    Only says WHAT Grey is doing and how many sources it has — never how it
    is reasoning. Labels come from a fixed list in queries.py.
    """
    phase: ResearchPhase
    category: ResearchCategory | None = None   # None while evaluating all evidence
    label: str                                 # e.g. "Identifying relevant organizations"
    sources_found: int = 0                     # total kept so far
    high_quality_sources: int = 0              # Tier A kept so far


class ResearchSummary(BaseModel):
    """Totals shown in the research completion summary."""
    total_sources: int
    high_quality_count: int                    # Tier A
    by_tier: dict[EvidenceTier, int]
    by_category: dict[ResearchCategory, int]
    provider: str


class ResearchEvidenceOutput(BaseModel):
    """The skill's result. The workflow decides what happens next — the skill never does."""
    industry: str
    branch: str
    sources: list[EvidenceSource]              # normalized, de-duplicated, strongest first
    queries_run: list[str]                     # every search made, for transparency
    summary: ResearchSummary
