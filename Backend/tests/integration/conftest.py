"""
Shared fixtures for the API integration tests.

The `client` fixture runs real HTTP requests against the FastAPI app with:
  - an in-memory SQLite database (fresh per test)
  - a fresh LangGraph MemorySaver (fresh per test)
  - its own skill registry using the mock search provider with no delay

This means:
  - No files are created on disk.
  - Each test is fully isolated — no data leaks between tests.
  - The full stack is exercised: route → workflow → skill → repository → database.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.projects import get_discovery_graph
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.models import Base
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import build_discovery_graph
from app.domains.fyp.workflows.discovery import research_runner
from main import app


@pytest.fixture
async def client():
    """
    Provide an HTTP test client wired to test-only dependencies.
    FastAPI dependency_overrides let us swap real dependencies for test ones.
    """
    # --- In-memory database setup ---
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    # --- Fresh workflow graph with its own skills ---
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider())
    test_graph = build_discovery_graph(MemorySaver(), skills=skills)

    # --- Apply overrides ---
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_discovery_graph] = lambda: test_graph
    research_runner._active_research.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    # --- Teardown ---
    app.dependency_overrides.clear()
    research_runner._active_research.clear()
    await engine.dispose()
