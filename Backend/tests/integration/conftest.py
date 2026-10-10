"""
Shared fixtures for the API integration tests.

The `client` fixture runs real HTTP requests against the FastAPI app with:
  - an in-memory SQLite database (fresh per test)
  - a fresh LangGraph MemorySaver (fresh per test)
  - its own skill registry using the mock search provider with no delay
    and a fake-mode LLM gateway (FakeLLMProvider — never a real model)

This means:
  - No files are created on disk.
  - Each test is fully isolated — no data leaks between tests.
  - The full stack is exercised: route → workflow → skill → repository → database.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.ai_strategy import get_ai_strategy_graph
from app.api.datasets import get_dataset_graph
from app.api.fyp_design import get_fyp_design_graph
from app.api.project_definition import get_project_definition_graph
from app.api.projects import get_discovery_graph
from app.core.brain.database import get_session, get_session_factory
from app.core.brain.models import Base
from app.core.config.settings import Settings
from app.core.llm import build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.ai_strategy import build_ai_strategy_graph
from app.domains.fyp.workflows.ai_strategy import runner as ai_runner
from app.domains.fyp.workflows.dataset_discovery import build_dataset_graph
from app.domains.fyp.workflows.dataset_discovery import runner as dataset_runner
from app.domains.fyp.workflows.discovery import build_discovery_graph
from app.domains.fyp.workflows.discovery import problem_runner, research_runner
from app.domains.fyp.workflows.fyp_design import build_fyp_design_graph
from app.domains.fyp.workflows.fyp_design import runner as fyp_runner
from app.domains.fyp.workflows.project_definition import build_project_definition_graph
from app.domains.fyp.workflows.project_definition import runner as definition_runner
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
    register_fyp_skills(skills, MockSearchProvider(), build_llm_gateway(Settings(_env_file=None, llm_mode="fake")))
    test_graph = build_discovery_graph(MemorySaver(), skills=skills)
    test_fyp_graph = build_fyp_design_graph(MemorySaver(), skills=skills)
    test_definition_graph = build_project_definition_graph(MemorySaver(), skills=skills)
    test_ai_graph = build_ai_strategy_graph(MemorySaver(), skills=skills)
    test_dataset_graph = build_dataset_graph(MemorySaver(), skills=skills)

    # --- Apply overrides ---
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_discovery_graph] = lambda: test_graph
    app.dependency_overrides[get_fyp_design_graph] = lambda: test_fyp_graph
    app.dependency_overrides[get_project_definition_graph] = lambda: test_definition_graph
    app.dependency_overrides[get_ai_strategy_graph] = lambda: test_ai_graph
    app.dependency_overrides[get_dataset_graph] = lambda: test_dataset_graph
    research_runner._active_research.clear()
    problem_runner._active_extractions.clear()
    fyp_runner._active_designs.clear()
    definition_runner._active_definitions.clear()
    ai_runner._active_checks.clear()
    dataset_runner._active_searches.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    # --- Teardown ---
    app.dependency_overrides.clear()
    research_runner._active_research.clear()
    problem_runner._active_extractions.clear()
    fyp_runner._active_designs.clear()
    definition_runner._active_definitions.clear()
    ai_runner._active_checks.clear()
    dataset_runner._active_searches.clear()
    await engine.dispose()
