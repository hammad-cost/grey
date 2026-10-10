"""
Integration tests for the technology stack and hardware routes (Release 0.10, Step 4).
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.technology import get_technology_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.technology_plan import build_technology_graph
from main import app
from tests.integration.test_fyp_design_api import stream
from tests.integration.test_models_api import dataset_selected_project, looked_project

PLAN_TYPES = ["technology_plan_started"] + ["technology_plan_progress"] * 3 + ["technology_plan_ready"]


async def models_approved_project(client: AsyncClient) -> str:
    workspace_id, ready = await looked_project(client)
    response = await client.post(f"/projects/{workspace_id}/models/approve",
                                 json={"plan_id": ready["data"]["models"]["plan"]["id"]})
    assert response.status_code == 200 and response.json()["allowed_actions"] == ["planTechnology"]
    return workspace_id


async def planned_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await models_approved_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/technology")
    return workspace_id, events[-1]


def use_llm_answers(answers: list):
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", answers)
    graph = build_technology_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_technology_graph] = lambda: graph


async def test_planning_streams_events_in_order(client: AsyncClient):
    workspace_id = await models_approved_project(client)
    status, content_type, events = await stream(client, f"/projects/{workspace_id}/technology")
    assert status == 200 and content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == PLAN_TYPES
    ready = events[-1]
    assert ready["stage"] == "TECHNOLOGY_PLAN" and ready["allowed_actions"] == ["approveTechnology", "replanTechnology"]
    assert ready["data"]["technology"]["plan"]["plan"]["hardware"]


async def test_planning_errors(client: AsyncClient):
    workspace_id = await dataset_selected_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/technology"))[0] == 409
    assert (await stream(client, "/projects/nope/technology"))[0] == 404
    workspace_id, _ = await planned_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/technology"))[0] == 409


async def test_a_failure_is_safe_and_can_be_retried(client: AsyncClient):
    workspace_id = await models_approved_project(client)
    use_llm_answers([LLMUnavailable("vendor outage (internal detail)")])
    _, _, events = await stream(client, f"/projects/{workspace_id}/technology")
    assert events[-1]["type"] == "technology_plan_failed" and events[-1]["allowed_actions"] == ["planTechnology"]
    assert "internal detail" not in str(events)
    _, _, retry = await stream(client, f"/projects/{workspace_id}/technology")
    assert retry[-1]["type"] == "technology_plan_ready"


async def test_replan_and_its_errors(client: AsyncClient):
    workspace_id, _ = await planned_project(client)
    status, _, events = await stream(client, f"/projects/{workspace_id}/technology/replan", {"preference": "simpler"})
    assert status == 200 and events[-1]["data"]["technology"]["plan"]["replans_used"] == 1
    assert (await stream(client, f"/projects/{workspace_id}/technology/replan", {"preference": "fancier"}))[0] == 422


async def test_approval_ends_release_0_10(client: AsyncClient):
    workspace_id, ready = await planned_project(client)
    plan_id = ready["data"]["technology"]["plan"]["id"]
    assert (await client.post(f"/projects/{workspace_id}/technology/approve", json={"plan_id": "x"})).status_code == 409
    response = await client.post(f"/projects/{workspace_id}/technology/approve", json={"plan_id": plan_id})
    assert response.status_code == 200 and response.json()["stage"] == "TECHNOLOGY_APPROVED"
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "TECHNOLOGY_APPROVED" and brain["technology_plan"]["status"] == "approved"
    assert (await stream(client, f"/projects/{workspace_id}/technology/replan", {"preference": "simpler"}))[0] == 409


async def test_get_returns_the_plan(client: AsyncClient):
    workspace_id, _ = await planned_project(client)
    body = (await client.get(f"/projects/{workspace_id}/technology")).json()
    assert body["workflow_state"] == "TECHNOLOGY_PLAN" and body["technology"]["can_replan"] is True
    assert body["latest_run"]["status"] == "complete"
    assert (await client.get("/projects/nope/technology")).status_code == 404
