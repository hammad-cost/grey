"""
Pydantic schemas for the Workspace Brain.

These are the typed data shapes that the rest of the application works with.
The ORM model (models.py) talks to the database; these schemas are what
the repository returns to callers — pure Python objects, no database coupling.
"""
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """
    All possible stages of the FYP journey.
    Release 0.1 uses only the first three.
    The rest are defined now so the state machine can be extended later
    without changing this file.
    """
    INDUSTRY_SELECTION = "INDUSTRY_SELECTION"
    BRANCH_SELECTION = "BRANCH_SELECTION"
    EVIDENCE_RESEARCH = "EVIDENCE_RESEARCH"
    # Future states — not used in Release 0.1
    PROBLEM_OPTIONS = "PROBLEM_OPTIONS"
    PROBLEM_SELECTED = "PROBLEM_SELECTED"
    AREA_CLASSIFICATION = "AREA_CLASSIFICATION"
    FYP_DESIGN = "FYP_DESIGN"
    SCOPE = "SCOPE"
    DATASET_DISCOVERY = "DATASET_DISCOVERY"
    AI_STRATEGY = "AI_STRATEGY"
    TECHNOLOGY_PLAN = "TECHNOLOGY_PLAN"
    ARCHITECTURE = "ARCHITECTURE"
    EVALUATION = "EVALUATION"
    FEASIBILITY = "FEASIBILITY"
    SUPERVISOR_READINESS = "SUPERVISOR_READINESS"
    PROPOSAL_GENERATION = "PROPOSAL_GENERATION"
    COMPLETE = "COMPLETE"


class DecisionStatus(str, Enum):
    """
    Lifecycle of a single decision inside the Project Brain.
    A decision is not authoritative until it reaches APPROVED.
    """
    CANDIDATE = "candidate"
    RECOMMENDED = "recommended"
    SELECTED = "selected"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


# ── Evidence ──────────────────────────────────────────────────────────────────

class EvidenceTier(str, Enum):
    """
    How strong a source is (product blueprint §11 "Evidence Quality").

    A — Primary evidence: official startup/company website, government
        publication or initiative, peer-reviewed research, official dataset,
        official technical documentation.
    B — Strong secondary evidence: reputable news, established technology or
        industry publication, university research announcement.
    C — Discovery evidence: startup directories, accelerator profiles,
        industry blogs, aggregators, community discussions.
        Useful for discovering ideas; final FYP recommendations should be
        backed by A or B evidence.
    """
    A = "A"
    B = "B"
    C = "C"


class SourceType(str, Enum):
    """What kind of source this is (product blueprint §9 "Evidence Research")."""
    STARTUP = "startup"
    COMPANY = "company"
    GOVERNMENT_INITIATIVE = "government_initiative"
    GOVERNMENT_REPORT = "government_report"
    OFFICIAL_PROGRAM = "official_program"
    NEWS = "news"
    RESEARCH_PAPER = "research_paper"
    UNIVERSITY_RESEARCH = "university_research"
    PUBLIC_CHALLENGE = "public_challenge"
    OPEN_SOURCE = "open_source"
    DATASET = "dataset"
    INDUSTRY_REPORT = "industry_report"
    OTHER = "other"


class ResearchCategory(str, Enum):
    """Which part of the research found this source. Matches the progress steps the student sees."""
    ORGANIZATIONS = "organizations"        # startups and companies
    OFFICIAL_SOURCES = "official_sources"  # government initiatives, reports, programs
    RESEARCH = "research"                  # papers and university research
    DATASETS = "datasets"                  # public datasets (found, not recommended)


class EvidenceSource(BaseModel):
    """
    One normalized piece of evidence, ready to be saved to the Project Brain.

    Every field the product blueprint requires for transparency (§10) is here.
    Text fields must not be empty — evidence without them is rejected.
    """
    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)          # company / agency / university behind it
    source_type: SourceType
    published_date: date | None = None               # not every source has a date
    url: str = Field(pattern=r"^https?://\S+$")
    problem_addressed: str = Field(min_length=1)     # the real problem this source is about
    relevant_insight: str = Field(min_length=1)      # what this source tells us
    why_it_matters: str = Field(min_length=1)        # why it is useful for the student's FYP
    evidence_tier: EvidenceTier
    research_category: ResearchCategory
    query: str = Field(min_length=1)                 # the search that found it (transparency)
    provider: str = Field(min_length=1)              # which search provider, e.g. "mock"


class StoredEvidenceSource(EvidenceSource):
    """An EvidenceSource as read back from the Project Brain, with its storage details."""
    id: str
    workspace_id: str
    research_run_id: str
    retrieved_at: datetime

    model_config = {"from_attributes": True}


# ── Research runs ─────────────────────────────────────────────────────────────

class ResearchStatus(str, Enum):
    """Lifecycle of one research attempt."""
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ResearchRun(BaseModel):
    """One attempt at evidence research for a project."""
    id: str
    workspace_id: str
    status: ResearchStatus
    provider: str
    started_at: datetime
    completed_at: datetime | None = None
    sources_found: int = 0
    high_quality_count: int = 0      # number of Tier A sources
    error: str | None = None

    model_config = {"from_attributes": True}


# ── Snapshot ──────────────────────────────────────────────────────────────────

class WorkspaceBrainSnapshot(BaseModel):
    """
    A read-only view of the current Project Brain state.
    This is what callers receive from WorkspaceBrainRepository.get_snapshot().
    """
    workspace_id: str
    workflow_state: WorkflowState

    industry: str | None = None
    industry_status: DecisionStatus | None = None

    branch: str | None = None
    branch_status: DecisionStatus | None = None

    # The latest research attempt (None until research has started).
    # The evidence itself is read separately with list_evidence().
    research: ResearchRun | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
