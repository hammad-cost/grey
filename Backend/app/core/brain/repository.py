"""
WorkspaceBrainRepository

The only place in the codebase that reads from and writes to the
Project Brain tables (workspace_brain, research_run, evidence_source,
problem_run, problem_candidate, problem_evidence, functional_area,
fyp_design_run, fyp_design, project_definition_run, project_definition,
scope_item, ai_strategy_run, ai_strategy, dataset_run, dataset_plan).
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
    AIStrategyRecord,
    AIStrategyRunRecord,
    DatasetPlanRecord,
    DatasetRunRecord,
    EvidenceSourceRecord,
    FunctionalAreaRecord,
    FYPDesignRecord,
    FYPDesignRunRecord,
    ProblemCandidateRecord,
    ProblemEvidenceRecord,
    ProblemRunRecord,
    ProjectDefinitionRecord,
    ProjectDefinitionRunRecord,
    ResearchRunRecord,
    ScopeItemRecord,
    WorkspaceBrainRecord,
)
from app.core.brain.ai_strategy_rules import check_strategy, recheck_problem
from app.core.brain.dataset_rules import check_plan, research_problem
from app.core.brain.schemas import (
    MAX_AI_STRATEGY_RECHECKS,
    MAX_DATASET_RESEARCHES,
    MAX_FYP_ADJUSTMENTS,
    AIStrategy,
    AIStrategyPreference,
    AIStrategyRun,
    AIStrategyRunStatus,
    AIStrategyStatus,
    DatasetCandidate,
    DatasetChoice,
    DatasetPlan,
    DatasetPlanStatus,
    DatasetPreference,
    DatasetRun,
    DatasetRunStatus,
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
    ProjectDefinition,
    ProjectDefinitionRun,
    ProjectDefinitionRunStatus,
    ProjectDefinitionStatus,
    ResearchRun,
    ScopeKind,
    ResearchStatus,
    StoredEvidenceSource,
    StoredFunctionalArea,
    StoredFYPDesign,
    StoredProblemCandidate,
    StoredAIStrategy,
    StoredDatasetPlan,
    StoredProjectDefinition,
    StoredScopeItem,
    WorkflowState,
    WorkspaceBrainSnapshot,
)
from app.core.brain.scope_rules import move_scope_item, sort_scope

# A run still marked "running" after this long is assumed to have died
# (e.g. the server stopped mid-research) and no longer blocks a new run.
STALE_RESEARCH_AFTER = timedelta(minutes=10)

# The same rule for problem-extraction runs.
STALE_PROBLEM_RUN_AFTER = timedelta(minutes=10)

# The same rule for FYP design runs (Release 0.5).
STALE_FYP_DESIGN_RUN_AFTER = timedelta(minutes=10)

# The same rule for project definition runs (Release 0.6).
STALE_PROJECT_DEFINITION_RUN_AFTER = timedelta(minutes=10)

# The same rule for AI necessity checks (Release 0.7).
STALE_AI_STRATEGY_RUN_AFTER = timedelta(minutes=10)

# The same rule for dataset searches (Release 0.8).
STALE_DATASET_RUN_AFTER = timedelta(minutes=10)

# The same rule for project definition runs (Release 0.6).
STALE_PROJECT_DEFINITION_RUN_AFTER = timedelta(minutes=10)


class ResearchAlreadyRunningError(Exception):
    """Raised when research is started for a project that already has a run in progress."""


class ProblemRunAlreadyRunningError(Exception):
    """Raised when problem extraction is started for a project that already has a run in progress."""


class ProblemSelectionError(ValueError):
    """Raised when a problem cannot be selected (wrong stage, or not one of the project's options)."""


class FYPDesignRunAlreadyRunningError(Exception):
    """Raised when an FYP design is started for a project that already has one in progress."""


class ProjectDefinitionRunAlreadyRunningError(Exception):
    """Raised when the project definition is already being written for a workspace."""


class ProjectDefinitionError(ValueError):
    """The project definition or scope step is not allowed right now."""


class ProjectDefinitionRunAlreadyRunningError(Exception):
    """Raised when the project definition is already being written for a workspace."""


class ProjectDefinitionError(ValueError):
    """The project definition or scope step is not allowed right now."""


class AIStrategyRunAlreadyRunningError(Exception):
    """Raised when an AI necessity check is already running for a workspace."""


class AIStrategyError(ValueError):
    """The AI necessity check, a re-check or the approval is not allowed right now."""


class DatasetRunAlreadyRunningError(Exception):
    """A dataset search is already running for this project."""


class DatasetError(ValueError):
    """The dataset step isn't allowed now (wrong stage, no re-searches left, …)."""


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
        snapshot.project_definition = await self.get_project_definition(record.workspace_id)
        snapshot.project_definition_run = await self.get_latest_project_definition_run(record.workspace_id)
        snapshot.ai_strategy = await self.get_ai_strategy(record.workspace_id)
        snapshot.ai_strategy_run = await self.get_latest_ai_strategy_run(record.workspace_id)
        snapshot.dataset_plan = await self.get_dataset_plan(record.workspace_id)
        snapshot.dataset_run = await self.get_latest_dataset_run(record.workspace_id)
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

    # ── Project definition and scope (Release 0.6) ────────────────────────────

    async def _definition_record(self, workspace_id: str) -> ProjectDefinitionRecord | None:
        result = await self._session.execute(
            select(ProjectDefinitionRecord).where(ProjectDefinitionRecord.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def _scope_records(self, definition_id: str) -> list[ScopeItemRecord]:
        result = await self._session.execute(
            select(ScopeItemRecord).where(ScopeItemRecord.definition_id == definition_id)
        )
        return list(result.scalars().all())

    async def _latest_definition_run_record(self, workspace_id: str) -> ProjectDefinitionRunRecord | None:
        result = await self._session.execute(
            select(ProjectDefinitionRunRecord)
            .where(ProjectDefinitionRunRecord.workspace_id == workspace_id)
            .order_by(ProjectDefinitionRunRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_definition_run_record(self, run_id: str) -> ProjectDefinitionRunRecord:
        run = await self._session.get(ProjectDefinitionRunRecord, run_id)
        if run is None:
            raise ValueError(f"Project definition run '{run_id}' not found.")
        return run

    async def _to_stored_definition(self, record: ProjectDefinitionRecord) -> StoredProjectDefinition:
        items = [StoredScopeItem.model_validate(r) for r in await self._scope_records(record.id)]
        return StoredProjectDefinition(
            id=record.id,
            workspace_id=record.workspace_id,
            design_id=record.design_id,
            run_id=record.run_id,
            status=ProjectDefinitionStatus(record.status),
            problem_definition=record.problem_definition,
            proposed_solution=record.proposed_solution,
            scope=sort_scope(items),
            scope_changes=record.scope_changes,
            created_at=record.created_at,
            approved_at=record.approved_at,
        )

    async def get_project_definition(self, workspace_id: str) -> StoredProjectDefinition | None:
        """The project definition with its scope (draft or approved), or None until Grey has written it."""
        record = await self._definition_record(workspace_id)
        return await self._to_stored_definition(record) if record else None

    async def get_latest_project_definition_run(self, workspace_id: str) -> ProjectDefinitionRun | None:
        """The most recent attempt at writing the project definition, or None."""
        run = await self._latest_definition_run_record(workspace_id)
        return ProjectDefinitionRun.model_validate(run) if run else None

    async def start_project_definition_run(self, workspace_id: str) -> ProjectDefinitionRun:
        """
        Record that Grey has started writing the project definition. Allowed
        only at APPROVED_FYP, with an approved design and no definition yet
        (a failed attempt can be retried).

        Raises:
            ValueError:                               the project does not exist.
            ProjectDefinitionError:                   not allowed now (see above).
            ProjectDefinitionRunAlreadyRunningError:  an attempt is already in progress.
                A run stuck in "running" longer than STALE_PROJECT_DEFINITION_RUN_AFTER
                is marked failed instead, so a crashed run can't block forever.
        """
        workspace = await self._require_record(workspace_id)
        design = await self._current_design_record(workspace_id)
        if (
            workspace.workflow_state != WorkflowState.APPROVED_FYP.value
            or design is None
            or design.status != FYPDesignStatus.APPROVED.value
        ):
            raise ProjectDefinitionError(
                f"The project can only be defined after the FYP is approved (stage: {workspace.workflow_state})."
            )
        if await self._definition_record(workspace_id) is not None:
            raise ProjectDefinitionError("The project has already been defined.")

        latest = await self._latest_definition_run_record(workspace_id)
        if latest is not None and latest.status == ProjectDefinitionRunStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - _as_utc(latest.started_at)
            if age < STALE_PROJECT_DEFINITION_RUN_AFTER:
                raise ProjectDefinitionRunAlreadyRunningError(
                    f"The project definition is already being written for workspace '{workspace_id}'."
                )
            latest.status = ProjectDefinitionRunStatus.FAILED.value
            latest.error = "Project definition did not finish (marked as stale)."
            latest.completed_at = datetime.now(timezone.utc)

        run = ProjectDefinitionRunRecord(
            workspace_id=workspace_id,
            design_id=design.id,
            status=ProjectDefinitionRunStatus.RUNNING.value,
            # Set explicitly so a new run always sorts after the one it replaces.
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return ProjectDefinitionRun.model_validate(run)

    async def complete_project_definition_run(
        self,
        run_id: str,
        definition: ProjectDefinition,
        *,
        definition_id: str | None = None,
        item_ids: list[str] | None = None,
        provider: str,
        model: str,
        prompt_version: str,
    ) -> StoredProjectDefinition:
        """
        Save the project definition and its scope items, mark the run complete
        and move the project to SCOPE (the student reviews it) — in one commit.
        `definition_id` and `item_ids` (one per scope item, in order) let the
        workflow choose the ids, so its review step and the Brain agree.

        Raises:
            ValueError: the run does not exist or is not running, the project
                        isn't at APPROVED_FYP, it is already defined, or the
                        ids don't match the scope.
        """
        run = await self._require_definition_run_record(run_id)
        if run.status != ProjectDefinitionRunStatus.RUNNING.value:
            raise ValueError(f"Project definition run '{run_id}' is not running (status: {run.status}).")
        workspace = await self._require_record(run.workspace_id)
        if workspace.workflow_state != WorkflowState.APPROVED_FYP.value:
            raise ValueError(f"The project definition can't be saved now (stage: {workspace.workflow_state}).")
        if await self._definition_record(run.workspace_id) is not None:
            raise ValueError("The project has already been defined.")
        if item_ids is not None and len(item_ids) != len(definition.scope):
            raise ValueError("There must be one id per scope item.")

        record = ProjectDefinitionRecord(
            id=definition_id or str(uuid.uuid4()),
            workspace_id=run.workspace_id,
            design_id=run.design_id,
            run_id=run.id,
            status=ProjectDefinitionStatus.DRAFT.value,
            problem_definition=definition.problem_definition.model_dump(mode="json"),
            proposed_solution=definition.proposed_solution.model_dump(mode="json"),
            scope_changes=0,
        )
        self._session.add(record)

        positions: dict[ScopeKind, int] = {}
        for index, item in enumerate(definition.scope):
            position = positions.get(item.kind, 0)
            positions[item.kind] = position + 1
            self._session.add(ScopeItemRecord(
                id=item_ids[index] if item_ids else str(uuid.uuid4()),
                workspace_id=run.workspace_id,
                definition_id=record.id,
                kind=item.kind.value,
                position=position,
                title=item.title,
                description=item.description,
            ))

        run.status = ProjectDefinitionRunStatus.COMPLETE.value
        run.completed_at = datetime.now(timezone.utc)
        run.provider = provider
        run.model = model
        run.prompt_version = prompt_version

        workspace.workflow_state = WorkflowState.SCOPE.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return await self._to_stored_definition(record)

    async def fail_project_definition_run(self, run_id: str, error: str) -> ProjectDefinitionRun:
        """
        Mark an attempt at writing the project definition as failed.

        Raises:
            ValueError: the run does not exist.
        """
        run = await self._require_definition_run_record(run_id)

        run.status = ProjectDefinitionRunStatus.FAILED.value
        run.error = error
        run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return ProjectDefinitionRun.model_validate(run)

    async def _require_draft_definition(self, workspace_id: str) -> ProjectDefinitionRecord:
        workspace = await self._require_record(workspace_id)
        record = await self._definition_record(workspace_id)
        if (
            workspace.workflow_state != WorkflowState.SCOPE.value
            or record is None
            or record.status != ProjectDefinitionStatus.DRAFT.value
        ):
            raise ProjectDefinitionError(
                f"Project '{workspace_id}' has no scope to review (stage: {workspace.workflow_state})."
            )
        return record

    async def move_scope_item(self, workspace_id: str, item_id: str, to: ScopeKind) -> StoredProjectDefinition:
        """
        Move one feature to another list (core / optional / out of scope), following
        the scope rules in scope_rules.py. Only while the student reviews the scope.

        Raises:
            ValueError:             the project does not exist.
            ProjectDefinitionError: the scope isn't being reviewed.
            ScopeChangeError:       the move breaks a scope rule (e.g. too few core features).
        """
        record = await self._require_draft_definition(workspace_id)
        records = await self._scope_records(record.id)
        moved = move_scope_item([StoredScopeItem.model_validate(r) for r in records], item_id, to)

        new_place = next(item for item in moved if item.id == item_id)
        target = next(r for r in records if r.id == item_id)
        target.kind = new_place.kind.value
        target.position = new_place.position
        record.scope_changes += 1

        await self._session.commit()
        await self._session.refresh(record)
        return await self._to_stored_definition(record)

    async def approve_project_definition(self, workspace_id: str, definition_id: str) -> StoredProjectDefinition:
        """
        Record the student's approval of the scope (a mandatory decision).
        The project moves to SCOPE_APPROVED in the same commit.

        Raises:
            ValueError:             the project does not exist.
            ProjectDefinitionError: the scope isn't being reviewed, or `definition_id`
                                    isn't this project's definition.
        """
        record = await self._require_draft_definition(workspace_id)
        if record.id != definition_id:
            raise ProjectDefinitionError(f"'{definition_id}' is not this project's definition.")

        workspace = await self._require_record(workspace_id)
        record.status = ProjectDefinitionStatus.APPROVED.value
        record.approved_at = datetime.now(timezone.utc)
        workspace.workflow_state = WorkflowState.SCOPE_APPROVED.value
        workspace.updated_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(record)
        return await self._to_stored_definition(record)

    # ── AI necessity check and AI / ML strategy (Release 0.7) ────────────────

    async def _ai_strategy_record(self, workspace_id: str) -> AIStrategyRecord | None:
        result = await self._session.execute(
            select(AIStrategyRecord).where(AIStrategyRecord.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def _latest_ai_run_record(self, workspace_id: str) -> AIStrategyRunRecord | None:
        result = await self._session.execute(
            select(AIStrategyRunRecord)
            .where(AIStrategyRunRecord.workspace_id == workspace_id)
            .order_by(AIStrategyRunRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_ai_run_record(self, run_id: str) -> AIStrategyRunRecord:
        run = await self._session.get(AIStrategyRunRecord, run_id)
        if run is None:
            raise ValueError(f"AI strategy run '{run_id}' not found.")
        return run

    @staticmethod
    def _to_stored_ai_strategy(record: AIStrategyRecord) -> StoredAIStrategy:
        return StoredAIStrategy(
            id=record.id,
            workspace_id=record.workspace_id,
            definition_id=record.definition_id,
            run_id=record.run_id,
            status=AIStrategyStatus(record.status),
            strategy=record.strategy,
            rechecks_used=record.rechecks_used,
            preference=record.preference,
            created_at=record.created_at,
            updated_at=record.updated_at,
            approved_at=record.approved_at,
        )

    async def get_ai_strategy(self, workspace_id: str) -> StoredAIStrategy | None:
        """The AI strategy (draft or approved), or None until Grey has checked the project."""
        record = await self._ai_strategy_record(workspace_id)
        return self._to_stored_ai_strategy(record) if record else None

    async def get_latest_ai_strategy_run(self, workspace_id: str) -> AIStrategyRun | None:
        """The most recent AI necessity check (first check or re-check), or None."""
        run = await self._latest_ai_run_record(workspace_id)
        return AIStrategyRun.model_validate(run) if run else None

    async def start_ai_strategy_run(
        self, workspace_id: str, preference: AIStrategyPreference | None = None
    ) -> AIStrategyRun:
        """
        Record that Grey has started an AI necessity check.

        Without a preference (the first check): allowed only at SCOPE_APPROVED,
        with an approved definition and no strategy yet (a failed attempt can be retried).
        With a preference (a re-check): allowed only at AI_STRATEGY while the
        strategy is a draft, re-checks are left, and the preference makes sense
        for the current strategy (see ai_strategy_rules.recheck_problem).

        Raises:
            ValueError:                        the project does not exist.
            AIStrategyError:                   not allowed now (see above).
            AIStrategyRunAlreadyRunningError:  a check is already in progress.
                A run stuck in "running" longer than STALE_AI_STRATEGY_RUN_AFTER
                is marked failed instead, so a crashed run can't block forever.
        """
        workspace = await self._require_record(workspace_id)
        definition = await self._definition_record(workspace_id)
        strategy = await self._ai_strategy_record(workspace_id)

        if preference is None:
            if (
                workspace.workflow_state != WorkflowState.SCOPE_APPROVED.value
                or definition is None
                or definition.status != ProjectDefinitionStatus.APPROVED.value
            ):
                raise AIStrategyError(
                    f"Grey checks the AI need only after the scope is approved (stage: {workspace.workflow_state})."
                )
            if strategy is not None:
                raise AIStrategyError("The AI need has already been checked.")
        else:
            if (
                workspace.workflow_state != WorkflowState.AI_STRATEGY.value
                or strategy is None
                or strategy.status != AIStrategyStatus.DRAFT.value
            ):
                raise AIStrategyError(f"There is no AI strategy to check again (stage: {workspace.workflow_state}).")
            if strategy.rechecks_used >= MAX_AI_STRATEGY_RECHECKS:
                raise AIStrategyError(
                    f"All {MAX_AI_STRATEGY_RECHECKS} re-checks have been used. You can approve the AI strategy."
                )
            problem = recheck_problem(AIStrategy.model_validate(strategy.strategy), preference)
            if problem is not None:
                raise AIStrategyError(problem)

        latest = await self._latest_ai_run_record(workspace_id)
        if latest is not None and latest.status == AIStrategyRunStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - _as_utc(latest.started_at)
            if age < STALE_AI_STRATEGY_RUN_AFTER:
                raise AIStrategyRunAlreadyRunningError(
                    f"The AI need is already being checked for workspace '{workspace_id}'."
                )
            latest.status = AIStrategyRunStatus.FAILED.value
            latest.error = "AI necessity check did not finish (marked as stale)."
            latest.completed_at = datetime.now(timezone.utc)

        run = AIStrategyRunRecord(
            workspace_id=workspace_id,
            definition_id=definition.id,
            preference=preference.value if preference else None,
            status=AIStrategyRunStatus.RUNNING.value,
            # Set explicitly so a new run always sorts after the one it replaces.
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return AIStrategyRun.model_validate(run)

    async def complete_ai_strategy_run(
        self,
        run_id: str,
        strategy: AIStrategy,
        *,
        strategy_id: str | None = None,
        provider: str,
        model: str,
        prompt_version: str,
    ) -> StoredAIStrategy:
        """
        Save the result of an AI necessity check and mark the run complete, in one commit.

        First check: the strategy is created and the project moves to AI_STRATEGY
        (the student reviews it). `strategy_id` lets the workflow choose the id,
        so its review step and the Brain agree.
        Re-check: the draft strategy is replaced and one re-check is used up.

        Raises:
            ValueError:          the run does not exist or is not running, or the
                                 project isn't at the stage the run started from.
            AIStrategyRuleError: the strategy breaks a rule in ai_strategy_rules.py.
        """
        run = await self._require_ai_run_record(run_id)
        if run.status != AIStrategyRunStatus.RUNNING.value:
            raise ValueError(f"AI strategy run '{run_id}' is not running (status: {run.status}).")
        check_strategy(strategy)
        workspace = await self._require_record(run.workspace_id)
        record = await self._ai_strategy_record(run.workspace_id)
        now = datetime.now(timezone.utc)

        if run.preference is None:
            if workspace.workflow_state != WorkflowState.SCOPE_APPROVED.value or record is not None:
                raise ValueError(f"The AI strategy can't be saved now (stage: {workspace.workflow_state}).")
            record = AIStrategyRecord(
                id=strategy_id or str(uuid.uuid4()),
                workspace_id=run.workspace_id,
                definition_id=run.definition_id,
                run_id=run.id,
                status=AIStrategyStatus.DRAFT.value,
                strategy=strategy.model_dump(mode="json"),
                rechecks_used=0,
                created_at=now,
                updated_at=now,
            )
            self._session.add(record)
            workspace.workflow_state = WorkflowState.AI_STRATEGY.value
        else:
            if (
                workspace.workflow_state != WorkflowState.AI_STRATEGY.value
                or record is None
                or record.status != AIStrategyStatus.DRAFT.value
            ):
                raise ValueError(f"The AI strategy can't be replaced now (stage: {workspace.workflow_state}).")
            record.strategy = strategy.model_dump(mode="json")
            record.run_id = run.id
            record.rechecks_used += 1
            record.preference = run.preference
            record.updated_at = now

        run.status = AIStrategyRunStatus.COMPLETE.value
        run.completed_at = now
        run.provider = provider
        run.model = model
        run.prompt_version = prompt_version
        workspace.updated_at = now

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_stored_ai_strategy(record)

    async def fail_ai_strategy_run(self, run_id: str, error: str) -> AIStrategyRun:
        """
        Mark an AI necessity check as failed (a failed re-check doesn't use one up).

        Raises:
            ValueError: the run does not exist.
        """
        run = await self._require_ai_run_record(run_id)

        run.status = AIStrategyRunStatus.FAILED.value
        run.error = error
        run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return AIStrategyRun.model_validate(run)

    async def approve_ai_strategy(self, workspace_id: str, strategy_id: str) -> StoredAIStrategy:
        """
        Record the student's approval of the AI strategy (a mandatory decision).
        The project moves to AI_STRATEGY_APPROVED in the same commit.

        Raises:
            ValueError:      the project does not exist.
            AIStrategyError: there is no draft strategy, or `strategy_id` isn't this project's.
        """
        workspace = await self._require_record(workspace_id)
        record = await self._ai_strategy_record(workspace_id)
        if (
            workspace.workflow_state != WorkflowState.AI_STRATEGY.value
            or record is None
            or record.status != AIStrategyStatus.DRAFT.value
        ):
            raise AIStrategyError(f"There is no AI strategy to approve (stage: {workspace.workflow_state}).")
        if record.id != strategy_id:
            raise AIStrategyError(f"'{strategy_id}' is not this project's AI strategy.")

        now = datetime.now(timezone.utc)
        record.status = AIStrategyStatus.APPROVED.value
        record.approved_at = now
        workspace.workflow_state = WorkflowState.AI_STRATEGY_APPROVED.value
        workspace.updated_at = now

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_stored_ai_strategy(record)

    # ── Dataset discovery (Release 0.8) ───────────────────────────────────────

    async def _dataset_plan_record(self, workspace_id: str) -> DatasetPlanRecord | None:
        result = await self._session.execute(
            select(DatasetPlanRecord).where(DatasetPlanRecord.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def _latest_dataset_run_record(self, workspace_id: str) -> DatasetRunRecord | None:
        result = await self._session.execute(
            select(DatasetRunRecord)
            .where(DatasetRunRecord.workspace_id == workspace_id)
            .order_by(DatasetRunRecord.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_dataset_run_record(self, run_id: str) -> DatasetRunRecord:
        run = await self._session.get(DatasetRunRecord, run_id)
        if run is None:
            raise ValueError(f"Dataset run '{run_id}' not found.")
        return run

    @staticmethod
    def _to_dataset_run(run: DatasetRunRecord) -> DatasetRun:
        return DatasetRun(
            id=run.id,
            workspace_id=run.workspace_id,
            strategy_id=run.strategy_id,
            preference=run.preference,
            status=DatasetRunStatus(run.status),
            started_at=run.started_at,
            completed_at=run.completed_at,
            searches_used=run.searches_used or 0,
            candidates_found=len(run.candidates or []),
            provider=run.provider,
            model=run.model,
            prompt_version=run.prompt_version,
            error=run.error,
        )

    @staticmethod
    def _to_stored_dataset_plan(record: DatasetPlanRecord) -> StoredDatasetPlan:
        return StoredDatasetPlan(
            id=record.id,
            workspace_id=record.workspace_id,
            strategy_id=record.strategy_id,
            run_id=record.run_id,
            status=DatasetPlanStatus(record.status),
            plan=record.plan,
            researches_used=record.researches_used,
            preference=record.preference,
            selected=record.selected,
            created_at=record.created_at,
            updated_at=record.updated_at,
            selected_at=record.selected_at,
        )

    async def get_dataset_plan(self, workspace_id: str) -> StoredDatasetPlan | None:
        """The dataset recommendation (draft or selected), or None until Grey has searched."""
        record = await self._dataset_plan_record(workspace_id)
        return self._to_stored_dataset_plan(record) if record else None

    async def get_latest_dataset_run(self, workspace_id: str) -> DatasetRun | None:
        """The most recent dataset search (first search or re-search), or None."""
        run = await self._latest_dataset_run_record(workspace_id)
        return self._to_dataset_run(run) if run else None

    async def list_dataset_candidates(self, run_id: str) -> list[DatasetCandidate]:
        """The dataset pages a search run found (empty until it completes)."""
        run = await self._require_dataset_run_record(run_id)
        return [DatasetCandidate.model_validate(c) for c in run.candidates or []]

    async def start_dataset_run(
        self, workspace_id: str, preference: DatasetPreference | None = None
    ) -> DatasetRun:
        """
        Record that Grey has started a dataset search.

        Without a preference (the first search): allowed only at AI_STRATEGY_APPROVED,
        with an approved AI strategy and no recommendation yet (a failed attempt can be retried).
        With a preference (a re-search): allowed only at DATASET_DISCOVERY while the
        recommendation is a draft, re-searches are left, and the preference makes
        sense for it (see dataset_rules.research_problem).

        Raises:
            ValueError:                     the project does not exist.
            DatasetError:                   not allowed now (see above).
            DatasetRunAlreadyRunningError:  a search is already in progress.
                A run stuck in "running" longer than STALE_DATASET_RUN_AFTER
                is marked failed instead, so a crashed run can't block forever.
        """
        workspace = await self._require_record(workspace_id)
        strategy = await self._ai_strategy_record(workspace_id)
        plan = await self._dataset_plan_record(workspace_id)

        if preference is None:
            if (
                workspace.workflow_state != WorkflowState.AI_STRATEGY_APPROVED.value
                or strategy is None
                or strategy.status != AIStrategyStatus.APPROVED.value
            ):
                raise DatasetError(
                    f"Grey looks for datasets only after the AI strategy is approved (stage: {workspace.workflow_state})."
                )
            if plan is not None:
                raise DatasetError("Grey has already recommended datasets.")
        else:
            if (
                workspace.workflow_state != WorkflowState.DATASET_DISCOVERY.value
                or plan is None
                or plan.status != DatasetPlanStatus.DRAFT.value
            ):
                raise DatasetError(f"There are no datasets to search again (stage: {workspace.workflow_state}).")
            if plan.researches_used >= MAX_DATASET_RESEARCHES:
                raise DatasetError(
                    f"All {MAX_DATASET_RESEARCHES} new searches have been used. You can select a dataset."
                )
            problem = research_problem(DatasetPlan.model_validate(plan.plan), preference)
            if problem is not None:
                raise DatasetError(problem)

        latest = await self._latest_dataset_run_record(workspace_id)
        if latest is not None and latest.status == DatasetRunStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - _as_utc(latest.started_at)
            if age < STALE_DATASET_RUN_AFTER:
                raise DatasetRunAlreadyRunningError(
                    f"Grey is already looking for datasets for workspace '{workspace_id}'."
                )
            latest.status = DatasetRunStatus.FAILED.value
            latest.error = "Dataset search did not finish (marked as stale)."
            latest.completed_at = datetime.now(timezone.utc)

        run = DatasetRunRecord(
            workspace_id=workspace_id,
            strategy_id=strategy.id,
            preference=preference.value if preference else None,
            status=DatasetRunStatus.RUNNING.value,
            candidates=[],
            # Set explicitly so a new run always sorts after the one it replaces.
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return self._to_dataset_run(run)

    async def complete_dataset_run(
        self,
        run_id: str,
        plan: DatasetPlan,
        candidates: list[DatasetCandidate],
        *,
        searches_used: int,
        plan_id: str | None = None,
        provider: str,
        model: str,
        prompt_version: str,
    ) -> StoredDatasetPlan:
        """
        Save the result of a dataset search and mark the run complete, in one commit.

        `candidates` are the pages the search found; every public dataset in the
        plan must link to one of them (see dataset_rules.py).
        First search: the recommendation is created and the project moves to
        DATASET_DISCOVERY (the student reviews it). `plan_id` lets the workflow
        choose the id, so its review step and the Brain agree.
        Re-search: the draft is replaced and one re-search is used up.

        Raises:
            ValueError:        the run does not exist or is not running, or the
                               project isn't at the stage the run started from.
            DatasetRuleError:  the plan breaks a rule in dataset_rules.py.
        """
        run = await self._require_dataset_run_record(run_id)
        if run.status != DatasetRunStatus.RUNNING.value:
            raise ValueError(f"Dataset run '{run_id}' is not running (status: {run.status}).")
        workspace = await self._require_record(run.workspace_id)
        record = await self._dataset_plan_record(run.workspace_id)
        preference = DatasetPreference(run.preference) if run.preference else None
        previous = DatasetPlan.model_validate(record.plan) if record is not None else None
        check_plan(plan, {c.url for c in candidates}, preference=preference, previous=previous)
        now = datetime.now(timezone.utc)

        if preference is None:
            if workspace.workflow_state != WorkflowState.AI_STRATEGY_APPROVED.value or record is not None:
                raise ValueError(f"The datasets can't be saved now (stage: {workspace.workflow_state}).")
            record = DatasetPlanRecord(
                id=plan_id or str(uuid.uuid4()),
                workspace_id=run.workspace_id,
                strategy_id=run.strategy_id,
                run_id=run.id,
                status=DatasetPlanStatus.DRAFT.value,
                plan=plan.model_dump(mode="json"),
                researches_used=0,
                created_at=now,
                updated_at=now,
            )
            self._session.add(record)
            workspace.workflow_state = WorkflowState.DATASET_DISCOVERY.value
        else:
            if (
                workspace.workflow_state != WorkflowState.DATASET_DISCOVERY.value
                or record is None
                or record.status != DatasetPlanStatus.DRAFT.value
            ):
                raise ValueError(f"The datasets can't be replaced now (stage: {workspace.workflow_state}).")
            record.plan = plan.model_dump(mode="json")
            record.run_id = run.id
            record.researches_used += 1
            record.preference = run.preference
            record.updated_at = now

        run.status = DatasetRunStatus.COMPLETE.value
        run.completed_at = now
        run.searches_used = searches_used
        run.candidates = [c.model_dump(mode="json") for c in candidates]
        run.provider = provider
        run.model = model
        run.prompt_version = prompt_version
        workspace.updated_at = now

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_stored_dataset_plan(record)

    async def fail_dataset_run(self, run_id: str, error: str, *, searches_used: int = 0) -> DatasetRun:
        """
        Mark a dataset search as failed (a failed re-search doesn't use one up).

        Raises:
            ValueError: the run does not exist.
        """
        run = await self._require_dataset_run_record(run_id)

        run.status = DatasetRunStatus.FAILED.value
        run.error = error
        run.searches_used = searches_used
        run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        await self._session.refresh(run)
        return self._to_dataset_run(run)

    async def select_dataset(self, workspace_id: str, plan_id: str, choice: DatasetChoice) -> StoredDatasetPlan:
        """
        Record which recommended dataset the student selected (a mandatory decision).
        The project moves to DATASET_SELECTED in the same commit.

        Raises:
            ValueError:    the project does not exist.
            DatasetError:  there is no draft recommendation, or `plan_id` isn't this project's.
        """
        workspace = await self._require_record(workspace_id)
        record = await self._dataset_plan_record(workspace_id)
        if (
            workspace.workflow_state != WorkflowState.DATASET_DISCOVERY.value
            or record is None
            or record.status != DatasetPlanStatus.DRAFT.value
        ):
            raise DatasetError(f"There are no datasets to select from (stage: {workspace.workflow_state}).")
        if record.id != plan_id:
            raise DatasetError(f"'{plan_id}' is not this project's dataset recommendation.")

        now = datetime.now(timezone.utc)
        record.status = DatasetPlanStatus.SELECTED.value
        record.selected = choice.value
        record.selected_at = now
        workspace.workflow_state = WorkflowState.DATASET_SELECTED.value
        workspace.updated_at = now

        await self._session.commit()
        await self._session.refresh(record)
        return self._to_stored_dataset_plan(record)
