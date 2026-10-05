"""
ORM model for the Workspace Brain.

One row per student project. Stores the authoritative state of a student's
FYP journey. Chat history and LangGraph runtime state are NOT stored here —
only decisions that have been made and accepted.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
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
