"""
Tests for WorkspaceBrainRepository.

Uses an in-memory SQLite database so no files are created on disk and
tests run fast without affecting the real grey.db file.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.brain.models import Base
from app.core.brain.repository import WorkspaceBrainRepository
from app.core.brain.schemas import DecisionStatus, WorkflowState


# ── Shared test database setup ────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session() -> AsyncSession:
    """
    Create a fresh in-memory database and session for each test.
    Tables are created before the test and the engine is disposed after.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> WorkspaceBrainRepository:
    return WorkspaceBrainRepository(session)


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_create_workspace(repo: WorkspaceBrainRepository):
    """A new workspace starts at INDUSTRY_SELECTION with no decisions."""
    snapshot = await repo.create_workspace("ws-001")

    assert snapshot.workspace_id == "ws-001"
    assert snapshot.workflow_state == WorkflowState.INDUSTRY_SELECTION
    assert snapshot.industry is None
    assert snapshot.branch is None


async def test_get_snapshot_returns_none_for_unknown(repo: WorkspaceBrainRepository):
    """get_snapshot returns None when the workspace does not exist."""
    result = await repo.get_snapshot("does-not-exist")
    assert result is None


async def test_get_snapshot_returns_existing(repo: WorkspaceBrainRepository):
    """get_snapshot returns the correct workspace after creation."""
    await repo.create_workspace("ws-002")
    snapshot = await repo.get_snapshot("ws-002")

    assert snapshot is not None
    assert snapshot.workspace_id == "ws-002"


async def test_apply_industry_decision(repo: WorkspaceBrainRepository):
    """Saving an industry decision stores the value with APPROVED status."""
    await repo.create_workspace("ws-003")
    snapshot = await repo.apply_decision("ws-003", "industry", "Defense")

    assert snapshot.industry == "Defense"
    assert snapshot.industry_status == DecisionStatus.APPROVED
    assert snapshot.branch is None  # branch not yet chosen


async def test_apply_branch_decision(repo: WorkspaceBrainRepository):
    """Saving a branch decision stores both industry and branch correctly."""
    await repo.create_workspace("ws-004")
    await repo.apply_decision("ws-004", "industry", "Defense")
    snapshot = await repo.apply_decision("ws-004", "branch", "Navy")

    assert snapshot.industry == "Defense"
    assert snapshot.branch == "Navy"
    assert snapshot.branch_status == DecisionStatus.APPROVED


async def test_update_workflow_state(repo: WorkspaceBrainRepository):
    """update_workflow_state moves the project to the correct next stage."""
    await repo.create_workspace("ws-005")
    await repo.apply_decision("ws-005", "industry", "Defense")
    await repo.apply_decision("ws-005", "branch", "Navy")

    snapshot = await repo.update_workflow_state("ws-005", WorkflowState.EVIDENCE_RESEARCH)

    assert snapshot.workflow_state == WorkflowState.EVIDENCE_RESEARCH


async def test_full_release_01_journey(repo: WorkspaceBrainRepository):
    """
    End-to-end Release 0.1 flow:
    create → select industry → select branch → transition to EVIDENCE_RESEARCH
    """
    # 1. Student starts a project
    snap = await repo.create_workspace("ws-full")
    assert snap.workflow_state == WorkflowState.INDUSTRY_SELECTION

    # 2. Student selects industry
    snap = await repo.apply_decision("ws-full", "industry", "Healthcare")
    assert snap.industry == "Healthcare"

    # 3. Student selects branch
    snap = await repo.apply_decision("ws-full", "branch", "Clinical AI")
    assert snap.branch == "Clinical AI"

    # 4. Workflow transitions to EVIDENCE_RESEARCH
    snap = await repo.update_workflow_state("ws-full", WorkflowState.EVIDENCE_RESEARCH)
    assert snap.workflow_state == WorkflowState.EVIDENCE_RESEARCH

    # 5. Project Brain is consistent
    final = await repo.get_snapshot("ws-full")
    assert final.industry == "Healthcare"
    assert final.branch == "Clinical AI"
    assert final.workflow_state == WorkflowState.EVIDENCE_RESEARCH


async def test_apply_decision_raises_for_unknown_workspace(repo: WorkspaceBrainRepository):
    """apply_decision raises ValueError when workspace does not exist."""
    with pytest.raises(ValueError, match="not found"):
        await repo.apply_decision("ghost", "industry", "Defense")
