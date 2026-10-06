"""
WorkspaceBrainRepository

The only place in the codebase that reads from and writes to the
Project Brain tables (workspace_brain, research_run, evidence_source,
problem_run, problem_candidate, problem_evidence, functional_area,
fyp_design_run, fyp_design).
Everything else (API routes, workflows, skills) calls this repository —
they never touch the database directly.

This keeps the database swappable: change DATABASE_URL and the driver,
and this file continues to work without modification.
"""
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brain.models import (
    EvidenceSourceRecord,
    FunctionalAreaRecord,
    FYPDesignRecord,
    FYPDesignRunRecord,
    ProblemCandidateRecord,
    ProblemEvidenceRecord,
    ProblemRunRecord,
    ResearchRunRecord,
    WorkspaceBrainRecord,
)
from app.core.brain.schemas import (
    MAX_FYP_ADJUSTMENTS,
    MAX_PROBLEM_OPTIONS,
    DecisionStatus,
    EvidenceSource,
    EvidenceStrength,
    EvidenceTier,
    FunctionalArea,
    FYPAdjustment,
    FYPDesign,
    FYPDesignRun,
    FYPDesignRunKind,
    FYPDesignRunStatus,
    FYPDesignStatus,
    ProblemCandidate,
    ProblemRun,
    ProblemRunStatus,
    ProblemSourceDetail,
    ProblemStatus,
    ResearchRun,
    ResearchStatus,
    StoredEvidenceSource,
    StoredFunctionalArea,
    StoredFYPDesign,
    StoredProblemCandidate,
    WorkflowState,
    WorkspaceBrainSnapshot,
)

# A run still marked "running" after this long is assumed to have died
# (e.g. the server stopped mid-research) and no longer blocks a new run.
STALE_RESEARCH_AFTER = timedelta(minutes=10)

# The same rule for problem-extraction runs.
STALE_PROBLEM_RUN_AFTER = timedelta(minutes=10)

# The same rule for FYP design runs (Release 0.5).
STALE_FYP_DESIGN_RUN_AFTER = timedelta(minutes=10)


class ResearchAlreadyRunningError(Exception):
    """Raised when research is started for a project that already has a run in progress."""


class ProblemRunAlreadyRunningError(Exception):
    """Raised when problem extraction is started for a project that already has a run in progress."""


class ProblemSelectionError(ValueError):
    """Raised when a problem cannot be selected (wrong stage, or not one of the project's options)."""


class FYPDesignRunAlreadyRunningError(Exception):
    """Raised when an FYP design is started for a project that already has one in progress."""


class FYPDesignError(ValueError):
    """Raised when an FYP design step isn't allowed now (wrong stage, no redesigns left, not the current draft…)."""


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

    async def _latest_problem_run_record(self, workspace_id: str) -> ProblemRunRecord | None:
        result = await self._session.execute(
            select(ProblemRunRecord)
            .where(ProblemRunRecord.workspace_id == workspace_id)
            .order_by(ProblemRunRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_problem_run_record(self, run_id: str) -> ProblemRunRecord:
        run = await self._session.get(ProblemRunRecord, run_id)
        if run is None:
            raise ValueError(f"Problem run '{run_id}' not found.")
        return run

    async def _has_problem_options(self, workspace_id: str) -> bool:
        result = await self._session.execute(
            select(ProblemCandidateRecord.id)
            .where(ProblemCandidateRecord.workspace_id == workspace_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _to_stored_problems(
        self, records: list[ProblemCandidateRecord]
    ) -> list[StoredProblemCandidate]:
        """Attach each problem's cited sources (strongest first) and build the typed objects."""
        if not records:
            return []

        result = await self._session.execute(
            select(ProblemEvidenceRecord, EvidenceSourceRecord)
            .join(EvidenceSourceRecord, ProblemEvidenceRecord.evidence_source_id == EvidenceSourceRecord.id)
            .where(ProblemEvidenceRecord.problem_id.in_([r.id for r in records]))
            .order_by(EvidenceSourceRecord.evidence_tier.asc(), EvidenceSourceRecord.title.asc())
        )
        sources: dict[str, list[ProblemSourceDetail]] = {r.id: [] for r in records}
        for link, source in result.all():
            sources[link.problem_id].append(
                ProblemSourceDetail(
                    evidence_source_id=source.id,
                    supporting_point=link.supporting_point,
                    title=source.title,
                    organization=source.organization,
                    url=source.url,
                    source_type=source.source_type,
                    evidence_tier=source.evidence_tier,
                    published_date=source.published_date,
                )
            )

        return [
            StoredProblemCandidate(
                id=r.id,
                workspace_id=r.workspace_id,
                problem_run_id=r.problem_run_id,
                rank=r.rank,
                status=r.status,
                title=r.title,
                real_world_problem=r.real_world_problem,
                observed_solutions=r.observed_solutions,
                technical_problem=r.technical_problem,
                task_type=r.task_type,
                why_it_matters=r.why_it_matters,
                possible_fyp_direction=r.possible_fyp_direction,
                evidence=sources[r.id],
                evidence_strength=EvidenceStrength(
                    tier_a=r.tier_a_count, tier_b=r.tier_b_count, tier_c=r.tier_c_count
                ),
            )
            for r in records
        ]

    async def _selected_problem(self, workspace_id: str) -> StoredProblemCandidate | None:
        result = await self._session.execute(
            select(ProblemCandidateRecord).where(
                ProblemCandidateRecord.workspace_id == workspace_id,
                ProblemCandidateRecord.status == ProblemStatus.SELECTED.value,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return (await self._to_stored_problems([record]))[0]

    async def _to_snapshot(self, record: WorkspaceBrainRecord) -> WorkspaceBrainSnapshot:
        """Build a snapshot, including the latest research run, latest problem run and chosen problem."""
        snapshot = WorkspaceBrainSnapshot.model_validate(record)
        run = await self._latest_run_record(record.workspace_id)
        snapshot.research = ResearchRun.model_validate(run) if run else None
        problem_run = await self._latest_problem_run_record(record.workspace_id)
        snapshot.problem_run = ProblemRun.model_validate(problem_run) if problem_run else None
        snapshot.selected_problem = await self._selected_problem(record.workspace_id)
        snapshot.functional_area = await self.get_functional_area(record.workspace_id)
        snapshot.fyp_design = await self.get_current_fyp_design(record.workspace_id)
        snapshot.fyp_adjustments_used = await self.count_fyp_adjustments(record.workspace_id)
        snapshot.fyp_design_run = await self.get_latest_fyp_design_run(record.workspace_id)
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

    async def get_latest_problem_run(self, workspace_id: str) -> ProblemRun | None:
        """Return the most recent problem-extraction attempt for a project, or None."""
        run = await self._latest_problem_run_record(workspace_id)
        return ProblemRun.model_validate(run) if run else None

    async def list_problem_candidates(self, workspace_id: str) -> list[StoredProblemCandidate]:
        """Return the project's current problem options, strongest (rank 1) first, with their sources."""
        result = await self._session.execute(
            select(ProblemCandidateRecord)
            .where(ProblemCandidateRecord.workspace_id == workspace_id)
            .order_by(ProblemCandidateRecord.rank.asc())
        )
        return await self._to_stored_problems(list(result.scalars().all()))

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

        # Problem options cite this evidence, so it can't be swapped out underneath them.
        if await self._has_problem_options(run.workspace_id):
            raise ValueError("Evidence can't be replaced after problem options exist.")

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

    # ── Write: problem opportunities (Release 0.3) ────────────────────────────

    async def start_problem_run(self, workspace_id: str, research_run_id: str) -> ProblemRun:
        """
        Record that problem extraction has started, using the evidence of a completed research run.

        Raises:
            ValueError: the project does not exist, or the research run is not
                        a completed run of this project.
            ProblemRunAlreadyRunningError: an attempt is already in progress.
                A run stuck in "running" for longer than STALE_PROBLEM_RUN_AFTER
                is marked failed instead, so a crashed run can't block forever.
        """
        await self._require_record(workspace_id)

        research = await self._session.get(ResearchRunRecord, research_run_id)
        if (
            research is None
            or research.workspace_id != workspace_id
            or research.status != ResearchStatus.COMPLETE.value
        ):
            raise ValueError(
                f"Research run '{research_run_id}' is not a completed run of workspace '{workspace_id}'."
            )

        latest = await self._latest_problem_run_record(workspace_id)
        if latest is not None and latest.status == ProblemRunStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - _as_utc(latest.started_at)
            if age < STALE_PROBLEM_RUN_AFTER:
                raise ProblemRunAlreadyRunningError(
                    f"Problem extraction is already running for workspace '{workspace_id}'."
                )
            latest.status = ProblemRunStatus.FAILED.value
            latest.error = "Problem extraction did not finish (marked as stale)."
            latest.completed_at = datetime.now(timezone.utc)

        run = ProblemRunRecord(
            workspace_id=workspace_id,
            research_run_id=research_run_id,
            status=ProblemRunStatus.RUNNING.value,
            # Set explicitly so a new run always sorts after the one it replaces.
            started_at=datetime.now(timezone.utc),
            rejection_summary={},
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return ProblemRun.model_validate(run)

    async def complete_problem_run(
        self,
        run_id: str,
        candidates: list[ProblemCandidate],
        *,
        candidate_ids: list[str] | None = None,
        provider: str,
        model: str,
        prompt_version: str,
        candidates_generated: int,
        rejection_summary: dict[str, int] | None = None,
    ) -> ProblemRun:
        """
        Save the problem options from a finished run and mark the run complete.

        `candidates` must already be ordered strongest first; they are saved
        with rank 1, 2, 3… `candidate_ids` (optional, same order) lets the
        workflow choose the ids, so its selection step and the Brain agree.
        The project's previous options are replaced, and the
        project moves to PROBLEM_OPTIONS — all in one commit, so the Brain
        never holds half a result.

        Raises:
            ValueError: the run does not exist or is not running; a problem has
                        already been selected; there are no candidates or more
                        than MAX_PROBLEM_OPTIONS; a candidate cites the same
                        source twice or cites evidence this project doesn't have.
        """
        run = await self._require_problem_run_record(run_id)
        if run.status != ProblemRunStatus.RUNNING.value:
            raise ValueError(f"Problem run '{run_id}' is not running (status: {run.status}).")
        if await self._selected_problem(run.workspace_id) is not None:
            raise ValueError("A problem has already been selected for this project.")
        if not 1 <= len(candidates) <= MAX_PROBLEM_OPTIONS:
            raise ValueError(
                f"Expected 1–{MAX_PROBLEM_OPTIONS} problem options, got {len(candidates)}."
            )
        ids = candidate_ids or [str(uuid.uuid4()) for _ in candidates]
        if len(ids) != len(candidates) or len(set(ids)) != len(ids):
            raise ValueError("candidate_ids must give one unique id per candidate.")

        # Every cited source must be evidence stored for THIS project.
        result = await self._session.execute(
            select(EvidenceSourceRecord.id).where(
                EvidenceSourceRecord.workspace_id == run.workspace_id
            )
        )
        known_evidence = set(result.scalars().all())
        for candidate in candidates:
            cited = [link.evidence_source_id for link in candidate.evidence]
            if len(cited) != len(set(cited)):
                raise ValueError(f"Problem '{candidate.title}' cites the same source twice.")
            unknown = set(cited) - known_evidence
            if unknown:
                raise ValueError(
                    f"Problem '{candidate.title}' cites evidence this project doesn't have: {sorted(unknown)}"
                )

        # Replace the project's previous options with this run's options.
        old_ids = select(ProblemCandidateRecord.id).where(
            ProblemCandidateRecord.workspace_id == run.workspace_id
        )
        await self._session.execute(
            delete(ProblemEvidenceRecord).where(ProblemEvidenceRecord.problem_id.in_(old_ids))
        )
        await self._session.execute(
            delete(ProblemCandidateRecord).where(
                ProblemCandidateRecord.workspace_id == run.workspace_id
            )
        )

        for rank, (candidate_id, candidate) in enumerate(zip(ids, candidates), start=1):
            record = ProblemCandidateRecord(
                id=candidate_id,
                workspace_id=run.workspace_id,
                problem_run_id=run.id,
                rank=rank,
                status=ProblemStatus.CANDIDATE.value,
                title=candidate.title,
                real_world_problem=candidate.real_world_problem,
                observed_solutions=candidate.observed_solutions,
                technical_problem=candidate.technical_problem,
                task_type=candidate.task_type.value,
                why_it_matters=candidate.why_it_matters,
                possible_fyp_direction=candidate.possible_fyp_direction,
                tier_a_count=candidate.evidence_strength.tier_a,
                tier_b_count=candidate.evidence_strength.tier_b,
                tier_c_count=candidate.evidence_strength.tier_c,
            )
            self._session.add(record)
            for link in candidate.evidence:
                self._session.add(
                    ProblemEvidenceRecord(
                        problem_id=record.id,
                        evidence_source_id=link.evidence_source_id,
                        supporting_point=link.supporting_point,
                    )
                )

        run.status = ProblemRunStatus.COMPLETE.value
        run.completed_at = datetime.now(timezone.utc)
        run.provider = provider
        run.model = model
        run.prompt_version = prompt_version
        run.candidates_generated = candidates_generated
        run.candidates_kept = len(candidates)
        run.rejection_summary = dict(rejection_summary or {})

        workspace = await self._require_record(run.workspace_id)
        workspace.workflow_state = WorkflowState.PROBLEM_OPTIONS.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return ProblemRun.model_validate(run)

    async def fail_problem_run(self, run_id: str, error: str) -> ProblemRun:
        """
        Mark a problem run as failed. Options from an earlier successful run are kept.

        Raises:
            ValueError: the run does not exist.
        """
        run = await self._require_problem_run_record(run_id)

        run.status = ProblemRunStatus.FAILED.value
        run.error = error
        run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return ProblemRun.model_validate(run)

    async def select_problem(self, workspace_id: str, problem_id: str) -> StoredProblemCandidate:
        """
        Record the student's chosen problem (a mandatory decision, blueprint §15).

        The chosen option becomes "selected"; the others stay "candidate" (nothing
        is deleted). The project moves to PROBLEM_SELECTED in the same commit.

        Raises:
            ValueError: the project does not exist.
            ProblemSelectionError: the project is not choosing a problem right now,
                                   or `problem_id` is not one of its options.
        """
        workspace = await self._require_record(workspace_id)
        if workspace.workflow_state != WorkflowState.PROBLEM_OPTIONS.value:
            raise ProblemSelectionError(
                f"Project '{workspace_id}' is not choosing a problem (stage: {workspace.workflow_state})."
            )

        candidate = await self._session.get(ProblemCandidateRecord, problem_id)
        if candidate is None or candidate.workspace_id != workspace_id:
            raise ProblemSelectionError(f"'{problem_id}' is not one of this project's problem options.")

        candidate.status = ProblemStatus.SELECTED.value
        workspace.workflow_state = WorkflowState.PROBLEM_SELECTED.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(candidate)
        return (await self._to_stored_problems([candidate]))[0]

    # ── From problem to FYP (Release 0.5) ─────────────────────────────────────

    async def _latest_fyp_run_record(self, workspace_id: str) -> FYPDesignRunRecord | None:
        result = await self._session.execute(
            select(FYPDesignRunRecord)
            .where(FYPDesignRunRecord.workspace_id == workspace_id)
            .order_by(FYPDesignRunRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_fyp_run_record(self, run_id: str) -> FYPDesignRunRecord:
        run = await self._session.get(FYPDesignRunRecord, run_id)
        if run is None:
            raise ValueError(f"FYP design run '{run_id}' not found.")
        return run

    async def _current_design_record(self, workspace_id: str) -> FYPDesignRecord | None:
        """The newest version that isn't superseded: the draft, or the approved design."""
        result = await self._session.execute(
            select(FYPDesignRecord)
            .where(
                FYPDesignRecord.workspace_id == workspace_id,
                FYPDesignRecord.status != FYPDesignStatus.SUPERSEDED.value,
            )
            .order_by(FYPDesignRecord.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_functional_area(self, workspace_id: str) -> StoredFunctionalArea | None:
        """Where the chosen problem sits, or None until Grey has classified it."""
        record = await self._session.get(FunctionalAreaRecord, workspace_id)
        return StoredFunctionalArea.model_validate(record) if record else None

    async def get_current_fyp_design(self, workspace_id: str) -> StoredFYPDesign | None:
        """The design the student is reviewing (the draft) or has approved, or None."""
        record = await self._current_design_record(workspace_id)
        return StoredFYPDesign.model_validate(record) if record else None

    async def list_fyp_designs(self, workspace_id: str) -> list[StoredFYPDesign]:
        """Every version of the design, oldest (version 1) first."""
        result = await self._session.execute(
            select(FYPDesignRecord)
            .where(FYPDesignRecord.workspace_id == workspace_id)
            .order_by(FYPDesignRecord.version.asc())
        )
        return [StoredFYPDesign.model_validate(r) for r in result.scalars().all()]

    async def count_fyp_adjustments(self, workspace_id: str) -> int:
        """How many redesigns the student has used (only successful ones count)."""
        result = await self._session.execute(
            select(func.count())
            .select_from(FYPDesignRecord)
            .where(FYPDesignRecord.workspace_id == workspace_id, FYPDesignRecord.adjustment.is_not(None))
        )
        return int(result.scalar_one())

    async def get_latest_fyp_design_run(self, workspace_id: str) -> FYPDesignRun | None:
        """The most recent design attempt, or None."""
        run = await self._latest_fyp_run_record(workspace_id)
        return FYPDesignRun.model_validate(run) if run else None

    async def start_fyp_design_run(
        self,
        workspace_id: str,
        kind: FYPDesignRunKind,
        adjustment: FYPAdjustment | None = None,
        note: str | None = None,
    ) -> FYPDesignRun:
        """
        Record that Grey has started designing (or redesigning) the FYP.

        INITIAL:    a problem is chosen and there is no design yet (stage
                    PROBLEM_SELECTED, or AREA_CLASSIFICATION after a failed attempt).
        ADJUSTMENT: the student asked for a redesign of the current draft
                    (stage FYP_DESIGN, fewer than MAX_FYP_ADJUSTMENTS used).

        Raises:
            ValueError:                       the project does not exist.
            FYPDesignError:                   not allowed now (see above).
            FYPDesignRunAlreadyRunningError:  an attempt is already in progress.
                A run stuck in "running" longer than STALE_FYP_DESIGN_RUN_AFTER is
                marked failed instead, so a crashed run can't block forever.
        """
        workspace = await self._require_record(workspace_id)
        problem = await self._selected_problem(workspace_id)
        if problem is None:
            raise FYPDesignError("The FYP can only be designed after a problem has been chosen.")

        stage = workspace.workflow_state
        current = await self._current_design_record(workspace_id)
        if kind == FYPDesignRunKind.INITIAL:
            allowed = {WorkflowState.PROBLEM_SELECTED.value, WorkflowState.AREA_CLASSIFICATION.value}
            if stage not in allowed or current is not None:
                raise FYPDesignError(f"The FYP has already been designed (stage: {stage}).")
            adjustment, note = None, None
        else:
            if (
                stage != WorkflowState.FYP_DESIGN.value
                or current is None
                or current.status != FYPDesignStatus.DRAFT.value
            ):
                raise FYPDesignError(f"There is no FYP design to adjust right now (stage: {stage}).")
            if adjustment is None:
                raise FYPDesignError("A redesign needs an adjustment.")
            if await self.count_fyp_adjustments(workspace_id) >= MAX_FYP_ADJUSTMENTS:
                raise FYPDesignError(f"All {MAX_FYP_ADJUSTMENTS} redesigns have been used.")

        latest = await self._latest_fyp_run_record(workspace_id)
        if latest is not None and latest.status == FYPDesignRunStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - _as_utc(latest.started_at)
            if age < STALE_FYP_DESIGN_RUN_AFTER:
                raise FYPDesignRunAlreadyRunningError(
                    f"An FYP design is already running for workspace '{workspace_id}'."
                )
            latest.status = FYPDesignRunStatus.FAILED.value
            latest.error = "FYP design did not finish (marked as stale)."
            latest.completed_at = datetime.now(timezone.utc)

        run = FYPDesignRunRecord(
            workspace_id=workspace_id,
            problem_id=problem.id,
            kind=kind.value,
            adjustment=adjustment.value if adjustment else None,
            note=note,
            status=FYPDesignRunStatus.RUNNING.value,
            # Set explicitly so a new run always sorts after the one it replaces.
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return FYPDesignRun.model_validate(run)

    async def save_functional_area(
        self,
        run_id: str,
        area: FunctionalArea,
        *,
        provider: str,
        model: str,
        prompt_version: str,
    ) -> StoredFunctionalArea:
        """
        Save where the chosen problem sits. The project moves to AREA_CLASSIFICATION
        in the same commit (the design itself is still to come).

        Raises:
            ValueError: the run does not exist or is not running, or the project
                        isn't at PROBLEM_SELECTED (e.g. the area is already saved).
        """
        run = await self._require_fyp_run_record(run_id)
        if run.status != FYPDesignRunStatus.RUNNING.value:
            raise ValueError(f"FYP design run '{run_id}' is not running (status: {run.status}).")
        workspace = await self._require_record(run.workspace_id)
        if workspace.workflow_state != WorkflowState.PROBLEM_SELECTED.value:
            raise ValueError(f"The functional area can't be saved now (stage: {workspace.workflow_state}).")

        record = FunctionalAreaRecord(
            workspace_id=run.workspace_id,
            problem_id=run.problem_id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            **area.model_dump(),
        )
        self._session.add(record)
        workspace.workflow_state = WorkflowState.AREA_CLASSIFICATION.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return StoredFunctionalArea.model_validate(record)

    async def complete_fyp_design_run(
        self,
        run_id: str,
        design: FYPDesign,
        *,
        design_id: str | None = None,
        provider: str,
        model: str,
        prompt_version: str,
    ) -> StoredFYPDesign:
        """
        Save a new version of the FYP design and mark the run complete.

        An INITIAL run saves version 1. An ADJUSTMENT run saves the next version
        and marks the previous draft "superseded" (nothing is deleted). Either
        way the project moves to FYP_DESIGN (the student reviews it) — all in
        one commit. `design_id` lets the workflow choose the id, so its review
        step and the Brain agree.

        Raises:
            ValueError: the run does not exist or is not running; the area isn't
                        saved yet; the stage or current design doesn't fit the
                        run's kind; or no redesigns are left.
        """
        run = await self._require_fyp_run_record(run_id)
        if run.status != FYPDesignRunStatus.RUNNING.value:
            raise ValueError(f"FYP design run '{run_id}' is not running (status: {run.status}).")
        workspace = await self._require_record(run.workspace_id)
        if await self._session.get(FunctionalAreaRecord, run.workspace_id) is None:
            raise ValueError("The functional area must be saved before the FYP design.")

        current = await self._current_design_record(run.workspace_id)
        if run.kind == FYPDesignRunKind.INITIAL.value:
            if workspace.workflow_state != WorkflowState.AREA_CLASSIFICATION.value or current is not None:
                raise ValueError(f"A first design can't be saved now (stage: {workspace.workflow_state}).")
            version = 1
        else:
            if (
                workspace.workflow_state != WorkflowState.FYP_DESIGN.value
                or current is None
                or current.status != FYPDesignStatus.DRAFT.value
            ):
                raise ValueError(f"A redesign can't be saved now (stage: {workspace.workflow_state}).")
            if await self.count_fyp_adjustments(run.workspace_id) >= MAX_FYP_ADJUSTMENTS:
                raise ValueError(f"All {MAX_FYP_ADJUSTMENTS} redesigns have been used.")
            current.status = FYPDesignStatus.SUPERSEDED.value
            version = current.version + 1

        record = FYPDesignRecord(
            id=design_id or str(uuid.uuid4()),
            workspace_id=run.workspace_id,
            problem_id=run.problem_id,
            run_id=run.id,
            version=version,
            status=FYPDesignStatus.DRAFT.value,
            adjustment=run.adjustment,
            note=run.note,
            **design.model_dump(),
        )
        self._session.add(record)

        run.status = FYPDesignRunStatus.COMPLETE.value
        run.completed_at = datetime.now(timezone.utc)
        run.provider = provider
        run.model = model
        run.prompt_version = prompt_version

        workspace.workflow_state = WorkflowState.FYP_DESIGN.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return StoredFYPDesign.model_validate(record)

    async def fail_fyp_design_run(self, run_id: str, error: str) -> FYPDesignRun:
        """
        Mark a design attempt as failed. A saved area and the current draft are kept.

        Raises:
            ValueError: the run does not exist.
        """
        run = await self._require_fyp_run_record(run_id)

        run.status = FYPDesignRunStatus.FAILED.value
        run.error = error
        run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return FYPDesignRun.model_validate(run)

    async def approve_fyp_design(self, workspace_id: str, design_id: str) -> StoredFYPDesign:
        """
        Record the student's approval of the current draft (a mandatory decision).
        The project moves to APPROVED_FYP in the same commit.

        Raises:
            ValueError:     the project does not exist.
            FYPDesignError: the project isn't reviewing a design, or `design_id`
                            isn't the current draft (e.g. an older version).
        """
        workspace = await self._require_record(workspace_id)
        if workspace.workflow_state != WorkflowState.FYP_DESIGN.value:
            raise FYPDesignError(
                f"Project '{workspace_id}' has no FYP design to approve (stage: {workspace.workflow_state})."
            )
        current = await self._current_design_record(workspace_id)
        if current is None or current.id != design_id or current.status != FYPDesignStatus.DRAFT.value:
            raise FYPDesignError(f"'{design_id}' is not this project's current FYP design.")

        current.status = FYPDesignStatus.APPROVED.value
        current.approved_at = datetime.now(timezone.utc)
        workspace.workflow_state = WorkflowState.APPROVED_FYP.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(current)
        return StoredFYPDesign.model_validate(current)
