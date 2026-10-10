"""
Integration tests for the dataset discovery API (Release 0.8, Step 5).

  POST /projects/{id}/datasets            — streams GreyEvents as newline-delimited JSON
  POST /projects/{id}/datasets/research   — streams a re-search with the student's preference
  POST /projects/{id}/datasets/select     — the student's selection (HITL resume)
  GET  /projects/{id}/datasets            — the recommendation and the latest search

Uses the shared `client` fixture from conftest.py (in-memory database, fresh
workflow graphs, mock search, fake-mode LLM — never a real model or search).
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.datasets import get_dataset_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.dataset_discovery import build_dataset_graph
from app.domains.fyp.workflows.dataset_discovery.events import FAILED_MESSAGE
from main import app
from tests.integration.test_ai_strategy_api import checked_project, scope_approved_project
from tests.integration.test_fyp_design_api import stream

SEARCH_TYPES = [
    "dataset_search_started",
    "dataset_search_progress",
    "dataset_search_progress",
    "dataset_search_progress",
    "dataset_search_progress",
    "dataset_options_ready",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def strategy_approved_project(client: AsyncClient) -> str:
    workspace_id, ready = await checked_project(client)
    strategy_id = ready["data"]["ai_strategy"]["strategy"]["id"]
    response = await client.post(f"/projects/{workspace_id}/ai-strategy/approve", json={"strategy_id": strategy_id})
    assert response.status_code == 200
    return workspace_id


def use_llm_answers(answers: list):
    """Swap the dataset graph for one whose (fake) model gives these answers first."""
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", answers)
    graph = build_dataset_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_dataset_graph] = lambda: graph


async def searched_project(client: AsyncClient) -> tuple[str, dict]:
    """A project with two datasets to choose from. Returns (id, the ready event)."""
    workspace_id = await strategy_approved_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/datasets")
    return workspace_id, events[-1]


# ── POST /projects/{id}/datasets ──────────────────────────────────────────────

async def test_the_search_streams_events_in_order(client: AsyncClient):
    workspace_id = await strategy_approved_project(client)

    status, content_type, events = await stream(client, f"/projects/{workspace_id}/datasets")

    assert status == 200
    assert content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == SEARCH_TYPES
    ready = events[-1]
    assert ready["stage"] == "DATASET_DISCOVERY"
    assert ready["status"] == "awaiting_user"
    assert ready["allowed_actions"] == ["selectDataset", "requestDatasetAlternative"]
    view = ready["data"]["datasets"]
    assert view["plan"]["status"] == "draft"
    assert view["plan"]["plan"]["primary"]["url"].startswith("https://")
    assert view["pages_found"] == 8
    assert ready["brain_patch"]["workflow_state"] == "DATASET_DISCOVERY"


async def test_the_search_needs_an_approved_ai_strategy(client: AsyncClient):
    workspace_id = await scope_approved_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/datasets")
    assert status == 409

    status, _, _ = await stream(client, "/projects/nope/datasets")
    assert status == 404


async def test_the_search_runs_once(client: AsyncClient):
    workspace_id, _ = await searched_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/datasets")
    assert status == 409


async def test_a_failure_is_safe_and_can_be_retried(client: AsyncClient):
    workspace_id = await strategy_approved_project(client)
    use_llm_answers([LLMUnavailable("vendor outage (internal detail)")])

    _, _, events = await stream(client, f"/projects/{workspace_id}/datasets")

    failed = events[-1]
    assert failed["type"] == "dataset_search_failed"
    assert failed["allowed_actions"] == ["findDatasets"]
    assert failed["data"]["message"] == FAILED_MESSAGE
    assert "internal detail" not in str(events)

    _, _, retry = await stream(client, f"/projects/{workspace_id}/datasets")
    assert retry[-1]["type"] == "dataset_options_ready"


# ── POST /projects/{id}/datasets/research ─────────────────────────────────────

async def test_a_research_streams_and_follows_the_preference(client: AsyncClient):
    workspace_id, _ = await searched_project(client)

    status, _, events = await stream(
        client, f"/projects/{workspace_id}/datasets/research", {"preference": "own_data"}
    )

    assert status == 200
    assert [e["type"] for e in events] == SEARCH_TYPES
    view = events[-1]["data"]["datasets"]
    assert view["plan"]["plan"]["primary"]["kind"] == "synthetic"
    assert view["plan"]["researches_used"] == 1
    assert view["available_researches"] == ["other_options"]


async def test_a_research_that_makes_no_sense_is_refused(client: AsyncClient):
    workspace_id, _ = await searched_project(client)
    await stream(client, f"/projects/{workspace_id}/datasets/research", {"preference": "own_data"})

    status, _, _ = await stream(client, f"/projects/{workspace_id}/datasets/research", {"preference": "own_data"})
    assert status == 409                                     # own data is already the primary


async def test_a_research_needs_a_known_preference(client: AsyncClient):
    workspace_id, _ = await searched_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/datasets/research", {"preference": "bigger"})
    assert status == 422


async def test_a_research_needs_datasets(client: AsyncClient):
    workspace_id = await strategy_approved_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/datasets/research", {"preference": "own_data"})
    assert status == 409


# ── POST /projects/{id}/datasets/select ───────────────────────────────────────

async def test_selection_ends_release_0_8(client: AsyncClient):
    workspace_id, ready = await searched_project(client)
    plan_id = ready["data"]["datasets"]["plan"]["id"]

    response = await client.post(
        f"/projects/{workspace_id}/datasets/select", json={"plan_id": plan_id, "choice": "primary"}
    )

    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "dataset_selected"
    assert event["stage"] == "DATASET_SELECTED"
    assert event["status"] == "complete"
    assert event["allowed_actions"] == []
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "DATASET_SELECTED"
    assert brain["dataset_plan"]["selected"] == "primary"


async def test_selection_errors(client: AsyncClient):
    workspace_id, ready = await searched_project(client)
    plan_id = ready["data"]["datasets"]["plan"]["id"]
    response = await client.post(f"/projects/{workspace_id}/datasets/select", json={"plan_id": "nope", "choice": "primary"})
    assert response.status_code == 409
    response = await client.post(f"/projects/{workspace_id}/datasets/select", json={"plan_id": plan_id, "choice": "both"})
    assert response.status_code == 422
    response = await client.post("/projects/nope/datasets/select", json={"plan_id": "x", "choice": "primary"})
    assert response.status_code == 404

    await client.post(f"/projects/{workspace_id}/datasets/select", json={"plan_id": plan_id, "choice": "primary"})
    response = await client.post(f"/projects/{workspace_id}/datasets/select", json={"plan_id": plan_id, "choice": "primary"})
    assert response.status_code == 409                       # already selected
    status, _, _ = await stream(client, f"/projects/{workspace_id}/datasets/research", {"preference": "other_options"})
    assert status == 409                                     # nothing changes after selection


# ── GET /projects/{id}/datasets ───────────────────────────────────────────────

async def test_get_returns_the_datasets_and_latest_run(client: AsyncClient):
    workspace_id, _ = await searched_project(client)

    response = await client.get(f"/projects/{workspace_id}/datasets")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_state"] == "DATASET_DISCOVERY"
    assert body["datasets"]["plan"]["plan"]["alternative"]["name"]
    assert body["datasets"]["uses_ai"] is True
    assert body["latest_run"]["status"] == "complete"
    assert body["latest_run"]["searches_used"] == 4


async def test_get_before_the_ai_strategy_is_approved(client: AsyncClient):
    workspace_id = await scope_approved_project(client)
    body = (await client.get(f"/projects/{workspace_id}/datasets")).json()
    assert body["datasets"] is None and body["latest_run"] is None
    response = await client.get("/projects/nope/datasets")
    assert response.status_code == 404
