"""
ORM models for the Workspace Brain.

workspace_brain — one row per student project: decisions and workflow position.
research_run    — one row per evidence-research attempt.
evidence_source — one row per piece of evidence found.
problem_run       — one row per problem-extraction attempt (Release 0.3).
problem_candidate — one row per problem option shown to the student.
problem_evidence  — which evidence supports which problem option.

Together they are the authoritative state of a student's FYP journey.
Chat history and LangGraph runtime state are NOT stored here —
only decisions and evidence that have been accepted.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class WorkspaceBrainRecord(Base):
    """
    Persisted state of a single FYP project (workspace).

    workflow_state tracks which stage the student is currently in.
    Each decision field (industry, branch, …) has a matching _status field
    that tracks whether the decision has been approved, rejected, etc.
    """

    __tablename__ = "workspace_brain"

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(String, unique=True, index=True)

    # ── Workflow position ─────────────────────────────────────────────────────
    # Values match WorkflowState enum in schemas.py
    workflow_state: Mapped[str] = mapped_column(String, default="INDUSTRY_SELECTION")

    # ── Discovery decisions ───────────────────────────────────────────────────
    # Each decision stores the value and its status (approved / rejected / etc.)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    industry_status: Mapped[str | None] = mapped_column(String, nullable=True)

    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    branch_status: Mapped[str | None] = mapped_column(String, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ResearchRunRecord(Base):
    """
    One attempt at evidence research for a project.

    A project can have several runs over time (e.g. a failed run, then a retry).
    Only one run per project may be "running" at a time.
    """

    __tablename__ = "research_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )

    # Values match ResearchStatus enum in schemas.py: running / complete / failed
    status: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)          # e.g. "mock"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Filled in when the run completes
    sources_found: Mapped[int] = mapped_column(Integer, default=0)
    high_quality_count: Mapped[int] = mapped_column(Integer, default=0)   # Tier A sources

    # Filled in when the run fails
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceSourceRecord(Base):
    """
    One piece of evidence found during research.

    Stores every field the product blueprint requires for evidence
    transparency (§10) plus its quality tier (§11).
    A project never stores the same URL twice.
    """

    __tablename__ = "evidence_source"
    __table_args__ = (UniqueConstraint("workspace_id", "url", name="uq_evidence_workspace_url"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    research_run_id: Mapped[str] = mapped_column(String, ForeignKey("research_run.id"), index=True)

    # ── What the source is ────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(Text)
    organization: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String)        # SourceType enum value
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    url: Mapped[str] = mapped_column(Text)

    # ── Why it matters for the student ────────────────────────────────────────
    problem_addressed: Mapped[str] = mapped_column(Text)
    relevant_insight: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)

    # ── Quality and origin ────────────────────────────────────────────────────
    evidence_tier: Mapped[str] = mapped_column(String)      # "A" / "B" / "C"
    research_category: Mapped[str] = mapped_column(String)  # ResearchCategory enum value
    query: Mapped[str] = mapped_column(Text)                # the search that found it
    provider: Mapped[str] = mapped_column(String)           # e.g. "mock"
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProblemRunRecord(Base):
    """
    One attempt at turning a project's evidence into problem options (Release 0.3).

    Like research runs, a project can have several attempts over time,
    and only one may be "running" at a time.
    """

    __tablename__ = "problem_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    research_run_id: Mapped[str] = mapped_column(String, ForeignKey("research_run.id"))

    # Values match ProblemRunStatus enum in schemas.py: running / complete / failed
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Filled in when the run completes: which LLM produced the options
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)

    # Quality counts: drafts the LLM returned, options kept, rejections by reason
    candidates_generated: Mapped[int] = mapped_column(Integer, default=0)
    candidates_kept: Mapped[int] = mapped_column(Integer, default=0)
    rejection_summary: Mapped[dict] = mapped_column(JSON, default=dict)

    # Filled in when the run fails
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProblemCandidateRecord(Base):
    """
    One problem option shown to the student (blueprint §13–14).

    Status is "candidate" until the student selects it; then exactly one
    option for the project becomes "selected".
    """

    __tablename__ = "problem_candidate"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    problem_run_id: Mapped[str] = mapped_column(String, ForeignKey("problem_run.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)               # 1 = strongest
    status: Mapped[str] = mapped_column(String)              # ProblemStatus enum value

    title: Mapped[str] = mapped_column(Text)
    real_world_problem: Mapped[str] = mapped_column(Text)
    observed_solutions: Mapped[str] = mapped_column(Text)
    technical_problem: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String)           # ProblemTaskType enum value
    why_it_matters: Mapped[str] = mapped_column(Text)
    possible_fyp_direction: Mapped[str] = mapped_column(Text)

    # Evidence strength, counted from the cited sources
    tier_a_count: Mapped[int] = mapped_column(Integer, default=0)
    tier_b_count: Mapped[int] = mapped_column(Integer, default=0)
    tier_c_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProblemEvidenceRecord(Base):
    """Links a problem option to a stored evidence source that supports it."""

    __tablename__ = "problem_evidence"

    problem_id: Mapped[str] = mapped_column(
        String, ForeignKey("problem_candidate.id"), primary_key=True
    )
    evidence_source_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_source.id"), primary_key=True
    )
    supporting_point: Mapped[str] = mapped_column(Text)
