"""
WorkspaceBrainRepository

The only place in the codebase that reads from and writes to the
Project Brain tables (workspace_brain, research_run, evidence_source).
Everything else (API routes, workflows, skills) calls this repository —
they never touch the database directly.

This keeps the database swappable: change DATABASE_URL and the driver,
and this file continues to work without modification.
"""
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brain.models import EvidenceSourceRecord, ResearchRunRecord, WorkspaceBrainRecord
from app.core.brain.schemas import (
    DecisionStatus,
    EvidenceSource,
    EvidenceTier,
    ResearchRun,
    ResearchStatus,
    StoredEvidenceSource,
    WorkflowState,
    WorkspaceBrainSnapshot,
)

# A run still marked "running" after this long is assumed to have died
# (e.g. the server stopped mid-research) and no longer blocks a new run.
STALE_RESEARCH_AFTER = timedelta(minutes=10)


class ResearchAlreadyRunningError(Exception):
    """Raised when research is started for a project that already has a run in progress."""


def _as_utc(value: datetime) -> datetime:
    """SQLite returns datetimes without a timezone; treat those as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class WorkspaceBrainRepository:
    """
    Reads and writes Project Brain state for one workspace (project).

    Usage:
        repo = WorkspaceBrainRepository(session)
        snapshot = await repo.get_snapshot(workspace_id)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_record(self, workspace_id: str) -> WorkspaceBrainRecord | None:
        result = await self._session.execute(
            select(WorkspaceBrainRecord).where(
                WorkspaceBrainRecord.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def _require_record(self, workspace_id: str) -> WorkspaceBrainRecord:
        record = await self._get_record(workspace_id)
        if record is None:
            raise ValueError(f"Workspace '{workspace_id}' not found.")
        return record

    async def _latest_run_record(self, workspace_id: str) -> ResearchRunRecord | None:
        result = await self._session.execute(
            select(ResearchRunRecord)
            .where(ResearchRunRecord.workspace_id == workspace_id)
            .order_by(ResearchRunRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_run_record(self, run_id: str) -> ResearchRunRecord:
        run = await self._session.get(ResearchRunRecord, run_id)
        if run is None:
            raise ValueError(f"Research run '{run_id}' not found.")
        return run

    async def _to_snapshot(self, record: WorkspaceBrainRecord) -> WorkspaceBrainSnapshot:
        """Build a snapshot, including the project's latest research run."""
        snapshot = WorkspaceBrainSnapshot.model_validate(record)
        run = await self._latest_run_record(record.workspace_id)
        snapshot.research = ResearchRun.model_validate(run) if run else None
        return snapshot

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_snapshot(self, workspace_id: str) -> WorkspaceBrainSnapshot | None:
        """
        Return the current state of a project, or None if it does not exist.
        """
        record = await self._get_record(workspace_id)
        if record is None:
            return None
        return await self._to_snapshot(record)

    async def get_latest_research_run(self, workspace_id: str) -> ResearchRun | None:
        """Return the most recent research attempt for a project, or None if there is none."""
        run = await self._latest_run_record(workspace_id)
        return ResearchRun.model_validate(run) if run else None

    async def list_evidence(self, workspace_id: str) -> list[StoredEvidenceSource]:
        """
        Return all evidence stored for a project, strongest first:
        Tier A before B before C, then newest first, then by title.
        """
        result = await self._session.execute(
            select(EvidenceSourceRecord)
            .where(EvidenceSourceRecord.workspace_id == workspace_id)
            .order_by(
                EvidenceSourceRecord.evidence_tier.asc(),
                EvidenceSourceRecord.published_date.desc().nulls_last(),
                EvidenceSourceRecord.title.asc(),
            )
        )
        return [StoredEvidenceSource.model_validate(r) for r in result.scalars().all()]

    # ── Write: decisions and workflow ─────────────────────────────────────────

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
        return await self._to_snapshot(record)

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
        record = await self._require_record(workspace_id)

        # Store the value and its status using Python's setattr so this
        # method stays generic — the caller names the field, not the method.
        setattr(record, field, value)
        setattr(record, f"{field}_status", status.value)
        record.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return await self._to_snapshot(record)

    async def update_workflow_state(
        self,
        workspace_id: str,
        state: WorkflowState,
    ) -> WorkspaceBrainSnapshot:
        """
        Move the project to the next workflow stage.
        Called by the LangGraph workflow after a required decision is made.
        """
        record = await self._require_record(workspace_id)

        record.workflow_state = state.value
        record.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return await self._to_snapshot(record)

    # ── Write: evidence research ──────────────────────────────────────────────

    async def start_research_run(self, workspace_id: str, provider: str) -> ResearchRun:
        """
        Record that research has started for a project.

        Raises:
            ValueError: the project does not exist.
            ResearchAlreadyRunningError: a run is already in progress.
                A run stuck in "running" for longer than STALE_RESEARCH_AFTER
                is marked failed instead, so a crashed run can't block forever.
        """
        await self._require_record(workspace_id)

        latest = await self._latest_run_record(workspace_id)
        if latest is not None and latest.status == ResearchStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - _as_utc(latest.started_at)
            if age < STALE_RESEARCH_AFTER:
                raise ResearchAlreadyRunningError(
                    f"Research is already running for workspace '{workspace_id}'."
                )
            latest.status = ResearchStatus.FAILED.value
            latest.error = "Research did not finish (marked as stale)."
            latest.completed_at = datetime.now(timezone.utc)

        run = ResearchRunRecord(
            workspace_id=workspace_id,
            status=ResearchStatus.RUNNING.value,
            provider=provider,
            # Set explicitly so a new run always sorts after the one it replaces.
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return ResearchRun.model_validate(run)

    async def complete_research_run(
        self,
        run_id: str,
        sources: list[EvidenceSource],
    ) -> ResearchRun:
        """
        Save the evidence from a finished run and mark the run complete.

        The project's previous evidence is replaced by this run's evidence.
        Everything happens in one commit, so the Brain never holds half a result.

        Raises:
            ValueError: the run does not exist, is not running,
                        or `sources` contains the same URL twice.
        """
        run = await self._require_run_record(run_id)
        if run.status != ResearchStatus.RUNNING.value:
            raise ValueError(f"Research run '{run_id}' is not running (status: {run.status}).")

        urls = [source.url for source in sources]
        if len(urls) != len(set(urls)):
            raise ValueError("Evidence contains duplicate URLs; de-duplicate before saving.")

        # Replace the project's previous evidence with this run's evidence.
        await self._session.execute(
            delete(EvidenceSourceRecord).where(
                EvidenceSourceRecord.workspace_id == run.workspace_id
            )
        )
        for source in sources:
            fields = {
                # Store enum members (e.g. SourceType.NEWS) as their plain value ("news").
                name: value.value if isinstance(value, Enum) else value
                for name, value in source.model_dump().items()
            }
            self._session.add(
                EvidenceSourceRecord(
                    workspace_id=run.workspace_id,
                    research_run_id=run.id,
                    **fields,
                )
            )

        run.status = ResearchStatus.COMPLETE.value
        run.completed_at = datetime.now(timezone.utc)
        run.sources_found = len(sources)
        run.high_quality_count = sum(1 for s in sources if s.evidence_tier == EvidenceTier.A)

        await self._session.commit()
        await self._session.refresh(run)
        return ResearchRun.model_validate(run)

    async def fail_research_run(self, run_id: str, error: str) -> ResearchRun:
        """
        Mark a run as failed. Evidence from earlier successful runs is kept.

        Raises:
            ValueError: the run does not exist.
        """
        run = await self._require_run_record(run_id)

        run.status = ResearchStatus.FAILED.value
        run.error = error
        run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return ResearchRun.model_validate(run)
