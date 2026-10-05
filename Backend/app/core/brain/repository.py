"""
WorkspaceBrainRepository

The only place in the codebase that reads from and writes to the
workspace_brain table. Everything else (API routes, workflows, skills)
calls this repository — they never touch the database directly.

This keeps the database swappable: change DATABASE_URL and the driver,
and this file continues to work without modification.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brain.models import WorkspaceBrainRecord
from app.core.brain.schemas import DecisionStatus, WorkflowState, WorkspaceBrainSnapshot


class WorkspaceBrainRepository:
    """
    Reads and writes Project Brain state for one workspace (project).

    Usage:
        repo = WorkspaceBrainRepository(session)
        snapshot = await repo.get_snapshot(workspace_id)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_snapshot(self, workspace_id: str) -> WorkspaceBrainSnapshot | None:
        """
        Return the current state of a project, or None if it does not exist.
        """
        result = await self._session.execute(
            select(WorkspaceBrainRecord).where(
                WorkspaceBrainRecord.workspace_id == workspace_id
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return WorkspaceBrainSnapshot.model_validate(record)

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create_workspace(self, workspace_id: str | None = None) -> WorkspaceBrainSnapshot:
        """
        Create a new project and return its initial snapshot.
        The project starts at INDUSTRY_SELECTION with no decisions made.
        """
        record = WorkspaceBrainRecord(
            workspace_id=workspace_id or str(uuid.uuid4()),
            workflow_state=WorkflowState.INDUSTRY_SELECTION,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return WorkspaceBrainSnapshot.model_validate(record)

    async def apply_decision(
        self,
        workspace_id: str,
        field: str,
        value: str,
        status: DecisionStatus = DecisionStatus.APPROVED,
    ) -> WorkspaceBrainSnapshot:
        """
        Record an approved decision (e.g. industry or branch) in the Project Brain.

        'field' is the name of the decision being stored: "industry" or "branch".
        'value' is what the student chose.
        'status' defaults to APPROVED because the student made an explicit selection.

        Example:
            await repo.apply_decision(workspace_id, "industry", "Defense")
        """
        result = await self._session.execute(
            select(WorkspaceBrainRecord).where(
                WorkspaceBrainRecord.workspace_id == workspace_id
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise ValueError(f"Workspace '{workspace_id}' not found.")

        # Store the value and its status using Python's setattr so this
        # method stays generic — the caller names the field, not the method.
        setattr(record, field, value)
        setattr(record, f"{field}_status", status.value)
        record.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return WorkspaceBrainSnapshot.model_validate(record)

    async def update_workflow_state(
        self,
        workspace_id: str,
        state: WorkflowState,
    ) -> WorkspaceBrainSnapshot:
        """
        Move the project to the next workflow stage.
        Called by the LangGraph workflow after a required decision is made.
        """
        result = await self._session.execute(
            select(WorkspaceBrainRecord).where(
                WorkspaceBrainRecord.workspace_id == workspace_id
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise ValueError(f"Workspace '{workspace_id}' not found.")

        record.workflow_state = state.value
        record.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return WorkspaceBrainSnapshot.model_validate(record)
