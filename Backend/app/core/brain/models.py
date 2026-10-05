"""
ORM models for the Workspace Brain.

workspace_brain — one row per student project: decisions and workflow position.
research_run    — one row per evidence-research attempt.
evidence_source — one row per piece of evidence found.

Together they are the authoritative state of a student's FYP journey.
Chat history and LangGraph runtime state are NOT stored here —
only decisions and evidence that have been accepted.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
