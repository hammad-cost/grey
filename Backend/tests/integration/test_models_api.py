"""
Integration tests for the pretrained models and APIs routes (Release 0.9, Step 5).
Shared `client` fixture: in-memory database, fresh graphs, mock search, fake LLM.
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.models import get_model_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.model_selection import build_model_graph
from app.domains.fyp.workflows.model_selection.events import FAILED_MESSAGE
from main import app
from tests.integration.test_datasets_api import searched_project, strategy_approved_project
from tests.integration.test_fyp_design_api import stream

SEARCH_TYPES = ["model_search_started"] + ["model_search_progress"] * 4 + ["models_ready"]


async def dataset_selected_project(client: AsyncClient) -> str:
    workspace_id, ready = await searched_project(client)
    plan_id = ready["data"]["datasets"]["plan"]["id"]
    response = await client.post(f"/projects/{workspace_id}/datasets/select", json={"plan_id": plan_id, "choice": "primary"})
    assert response.status_code == 200
    return workspace_id


async def looked_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await dataset_selected_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/models")
    return workspace_id, events[-1]


def use_llm_answers(answers: list):
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", answers)
    graph = build_model_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_model_graph] = lambda: graph


async def test_the_search_streams_events_in_order(client: AsyncClient):
    workspace_id = await dataset_selected_project(client)
    status, content_type, events = await stream(client, f"/projects/{workspace_id}/models")
    assert status == 200 and content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == SEARCH_TYPES
    ready = events[-1]
    assert ready["stage"] == "MODEL_SELECTION" and ready["status"] == "awaiting_user"
    assert ready["allowed_actions"] == ["approveModels", "requestOtherModels"]
    assert ready["data"]["models"]["plan"]["plan"]["options"][0]["url"].startswith("https://")


async def test_the_search_needs_a_selected_dataset_and_runs_once(client: AsyncClient):
    workspace_id = await strategy_approved_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/models"))[0] == 409
    assert (await stream(client, "/projects/nope/models"))[0] == 404
    workspace_id, _ = await looked_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/models"))[0] == 409


async def test_a_failure_is_safe_and_can_be_retried(client: AsyncClient):
    workspace_id = await dataset_selected_project(client)
    use_llm_answers([LLMUnavailable("vendor outage (internal detail)")])
    _, _, events = await stream(client, f"/projects/{workspace_id}/models")
    assert events[-1]["type"] == "model_search_failed"
    assert events[-1]["allowed_actions"] == ["findModels"]
    assert events[-1]["data"]["message"] == FAILED_MESSAGE
    assert "internal detail" not in str(events)
    _, _, retry = await stream(client, f"/projects/{workspace_id}/models")
    assert retry[-1]["type"] == "models_ready"


async def test_research_and_its_errors(client: AsyncClient):
    workspace_id, _ = await looked_project(client)
    status, _, events = await stream(client, f"/projects/{workspace_id}/models/research", {"preference": "other_options"})
    assert status == 200 and [e["type"] for e in events] == SEARCH_TYPES
    assert events[-1]["data"]["models"]["plan"]["researches_used"] == 1
    assert (await stream(client, f"/projects/{workspace_id}/models/research", {"preference": "bigger"}))[0] == 422


async def test_approval_ends_release_0_9(client: AsyncClient):
    workspace_id, ready = await looked_project(client)
    plan_id = ready["data"]["models"]["plan"]["id"]
    response = await client.post(f"/projects/{workspace_id}/models/approve", json={"plan_id": "nope"})
    assert response.status_code == 409
    response = await client.post(f"/projects/{workspace_id}/models/approve", json={"plan_id": plan_id})
    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "models_approved" and event["stage"] == "MODELS_APPROVED"
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "MODELS_APPROVED" and brain["model_plan"]["status"] == "approved"
    assert (await client.post(f"/projects/{workspace_id}/models/approve", json={"plan_id": plan_id})).status_code == 409
    assert (await stream(client, f"/projects/{workspace_id}/models/research", {"preference": "other_options"}))[0] == 409


async def test_get_returns_the_plan_and_latest_run(client: AsyncClient):
    workspace_id = await strategy_approved_project(client)
    body = (await client.get(f"/projects/{workspace_id}/models")).json()
    assert body["models"] is None and body["latest_run"] is None
    workspace_id, _ = await looked_project(client)
    body = (await client.get(f"/projects/{workspace_id}/models")).json()
    assert body["workflow_state"] == "MODEL_SELECTION"
    assert body["models"]["dataset_name"] and body["latest_run"]["status"] == "complete"
    assert (await client.get("/projects/nope/models")).status_code == 404
