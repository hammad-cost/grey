"""
ORM models for the Workspace Brain.

workspace_brain — one row per student project: decisions and workflow position.
research_run    — one row per evidence-research attempt.
evidence_source — one row per piece of evidence found.
problem_run       — one row per problem-extraction attempt (Release 0.3).
problem_candidate — one row per problem option shown to the student.
problem_evidence  — which evidence supports which problem option.
functional_area   — where the chosen problem sits (Release 0.5), one per project.
fyp_design_run    — one row per FYP design or redesign attempt (Release 0.5).
fyp_design        — one row per version of the FYP design (draft / superseded / approved).
project_definition_run — one row per attempt at writing the project definition (Release 0.6).
project_definition     — the problem definition and proposed solution, one per project.
scope_item             — one row per feature in the scope (core / optional / out of scope).

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


class FunctionalAreaRecord(Base):
    """Where the student's chosen problem sits (Release 0.5). One per project."""

    __tablename__ = "functional_area"

    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), primary_key=True
    )
    problem_id: Mapped[str] = mapped_column(String, ForeignKey("problem_candidate.id"))

    functional_area: Mapped[str] = mapped_column(Text)
    specific_area: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)

    # Which LLM classified it
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FYPDesignRunRecord(Base):
    """
    One attempt at designing the FYP (kind "initial") or redesigning it after
    the student asked for an adjustment (kind "adjustment"). Release 0.5.
    Only one may be "running" per project at a time.
    """

    __tablename__ = "fyp_design_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    problem_id: Mapped[str] = mapped_column(String, ForeignKey("problem_candidate.id"))

    kind: Mapped[str] = mapped_column(String)                       # FYPDesignRunKind value
    adjustment: Mapped[str | None] = mapped_column(String, nullable=True)   # FYPAdjustment value
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String)                     # FYPDesignRunStatus value
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Filled in when the run completes: which LLM produced the design
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)

    # Filled in when the run fails
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class FYPDesignRecord(Base):
    """
    One version of the student's FYP design (Release 0.5).

    Version 1 is the first design; each redesign adds a version and the
    previous draft becomes "superseded" (nothing is deleted). The student
    approves exactly one version.
    """

    __tablename__ = "fyp_design"
    __table_args__ = (UniqueConstraint("workspace_id", "version", name="uq_fyp_design_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    problem_id: Mapped[str] = mapped_column(String, ForeignKey("problem_candidate.id"))
    run_id: Mapped[str] = mapped_column(String, ForeignKey("fyp_design_run.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)                     # FYPDesignStatus value

    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    target_user: Mapped[str] = mapped_column(Text)
    system_input: Mapped[str] = mapped_column(Text)
    system_output: Mapped[str] = mapped_column(Text)
    main_contribution: Mapped[str] = mapped_column(Text)
    scope_reduction: Mapped[str] = mapped_column(Text)

    # What the student asked for to get this version (None for version 1)
    adjustment: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectDefinitionRunRecord(Base):
    """One attempt at writing the project definition and scope (Release 0.6)."""

    __tablename__ = "project_definition_run"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    design_id: Mapped[str] = mapped_column(String, ForeignKey("fyp_design.id"))

    status: Mapped[str] = mapped_column(String)                     # ProjectDefinitionRunStatus value
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Filled in when the run completes: which LLM wrote the definition
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)

    # Filled in when the run fails
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectDefinitionRecord(Base):
    """
    The problem definition and proposed solution for the approved FYP
    (Release 0.6). One per project; its features are scope_item rows.
    """

    __tablename__ = "project_definition"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), unique=True, index=True
    )
    design_id: Mapped[str] = mapped_column(String, ForeignKey("fyp_design.id"))
    run_id: Mapped[str] = mapped_column(String, ForeignKey("project_definition_run.id"))
    status: Mapped[str] = mapped_column(String)                     # ProjectDefinitionStatus value

    # Stored as JSON: they are always read and shown as a whole
    problem_definition: Mapped[dict] = mapped_column(JSON)          # ProblemDefinition
    proposed_solution: Mapped[dict] = mapped_column(JSON)           # ProposedSolution

    scope_changes: Mapped[int] = mapped_column(Integer, default=0)  # items the student moved

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScopeItemRecord(Base):
    """One feature in the project scope: core, optional or out of scope (Release 0.6)."""

    __tablename__ = "scope_item"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_brain.workspace_id"), index=True
    )
    definition_id: Mapped[str] = mapped_column(String, ForeignKey("project_definition.id"), index=True)

    kind: Mapped[str] = mapped_column(String)                       # ScopeKind value
    position: Mapped[int] = mapped_column(Integer)                  # order inside its list
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
