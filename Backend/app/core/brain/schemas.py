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
    NEWS = "news"                          # industry news (Release 0.4)


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


# ── Problem opportunities (Release 0.3) ───────────────────────────────────────

# The blueprint asks for a small number of strong problems (§13): 3–5.
MAX_PROBLEM_OPTIONS = 5


class ProblemTaskType(str, Enum):
    """The kind of technical task behind a problem. A fixed list, so the UI and later skills can rely on it."""
    ANOMALY_DETECTION = "anomaly_detection"
    CLASSIFICATION = "classification"
    FORECASTING = "forecasting"
    OPTIMIZATION = "optimization"
    NLP = "nlp"
    COMPUTER_VISION = "computer_vision"
    RECOMMENDATION = "recommendation"
    DECISION_SUPPORT = "decision_support"
    OTHER = "other"


class ProblemStatus(str, Enum):
    """A problem option is a candidate until the student selects it."""
    CANDIDATE = "candidate"
    SELECTED = "selected"


class EvidenceStrength(BaseModel):
    """How many cited sources of each tier back a problem. Counted by code, never by the LLM."""
    tier_a: int = Field(default=0, ge=0)
    tier_b: int = Field(default=0, ge=0)
    tier_c: int = Field(default=0, ge=0)


class ProblemEvidenceLink(BaseModel):
    """One piece of stored evidence that supports a problem, and the point it supports."""
    evidence_source_id: str = Field(min_length=1)
    supporting_point: str = Field(min_length=1)


class ProblemCandidate(BaseModel):
    """
    One validated problem opportunity, ready to be saved to the Project Brain.

    This is what the Problem Extraction skill returns. Every problem cites
    evidence that is already stored for the project (by its id), so the
    student can always see where the idea came from (blueprint §10, §14).
    """
    title: str = Field(min_length=1, max_length=120)          # e.g. "Abnormal vessel movement detection"
    real_world_problem: str = Field(min_length=1)            # the pain point organizations face
    observed_solutions: str = Field(min_length=1)            # what organizations are building (not the problem itself)
    technical_problem: str = Field(min_length=1)             # the underlying technical challenge
    task_type: ProblemTaskType
    why_it_matters: str = Field(min_length=1)
    possible_fyp_direction: str = Field(min_length=1)        # a student-sized project idea
    evidence: list[ProblemEvidenceLink] = Field(min_length=1)
    evidence_strength: EvidenceStrength


class ProblemSourceDetail(BaseModel):
    """A cited source as shown with a stored problem ("View sources")."""
    evidence_source_id: str
    supporting_point: str
    title: str
    organization: str
    url: str
    source_type: SourceType
    evidence_tier: EvidenceTier
    published_date: date | None = None


class StoredProblemCandidate(BaseModel):
    """A problem option as read back from the Project Brain, with its cited sources."""
    id: str
    workspace_id: str
    problem_run_id: str
    rank: int                               # 1 = strongest
    status: ProblemStatus
    title: str
    real_world_problem: str
    observed_solutions: str
    technical_problem: str
    task_type: ProblemTaskType
    why_it_matters: str
    possible_fyp_direction: str
    evidence: list[ProblemSourceDetail]
    evidence_strength: EvidenceStrength


class ProblemRunStatus(str, Enum):
    """Lifecycle of one problem-extraction attempt."""
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ProblemRun(BaseModel):
    """One attempt at turning a project's evidence into problem options."""
    id: str
    workspace_id: str
    research_run_id: str                    # the evidence this attempt used
    status: ProblemRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    # Which LLM produced the options (filled in when the run completes)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    # Quality counts: drafts the LLM returned, options kept, and why the rest were rejected
    candidates_generated: int = 0
    candidates_kept: int = 0
    rejection_summary: dict[str, int] = {}
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

    # The latest problem-extraction attempt and the student's chosen problem
    # (Release 0.3). The options are read separately with list_problem_candidates().
    problem_run: ProblemRun | None = None
    selected_problem: StoredProblemCandidate | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
