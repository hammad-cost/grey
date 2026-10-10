"""
Integration tests for the architecture and evaluation plan routes (Release 0.11, Step 4).
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.architecture import get_technical_plan_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.technical_plan import build_technical_plan_graph
from main import app
from tests.integration.test_fyp_design_api import stream
from tests.integration.test_technology_api import models_approved_project, planned_project

TYPES = ["architecture_started"] + ["architecture_progress"] * 3 + ["architecture_ready"]


async def technology_approved_project(client: AsyncClient) -> str:
    workspace_id, ready = await planned_project(client)
    response = await client.post(f"/projects/{workspace_id}/technology/approve",
                                 json={"plan_id": ready["data"]["technology"]["plan"]["id"]})
    assert response.status_code == 200 and response.json()["allowed_actions"] == ["designArchitecture"]
    return workspace_id


async def designed_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await technology_approved_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/architecture")
    return workspace_id, events[-1]


def use_llm_answers(answers: list):
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", answers)
    graph = build_technical_plan_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_technical_plan_graph] = lambda: graph


async def test_designing_streams_events_in_order(client: AsyncClient):
    workspace_id = await technology_approved_project(client)
    status, content_type, events = await stream(client, f"/projects/{workspace_id}/architecture")
    assert status == 200 and content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == TYPES
    ready = events[-1]
    assert ready["stage"] == "ARCHITECTURE"
    assert ready["allowed_actions"] == ["approveTechnicalPlan", "redesignArchitecture"]
    assert ready["data"]["technical_plan"]["plan"]["plan"]["architecture"]["flows"]


async def test_designing_errors(client: AsyncClient):
    workspace_id = await models_approved_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/architecture"))[0] == 409
    assert (await stream(client, "/projects/nope/architecture"))[0] == 404
    workspace_id, _ = await designed_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/architecture"))[0] == 409


async def test_a_failure_is_safe_and_can_be_retried(client: AsyncClient):
    workspace_id = await technology_approved_project(client)
    use_llm_answers([LLMUnavailable("vendor outage (internal detail)")])
    _, _, events = await stream(client, f"/projects/{workspace_id}/architecture")
    assert events[-1]["type"] == "architecture_failed" and events[-1]["allowed_actions"] == ["designArchitecture"]
    assert "internal detail" not in str(events)
    _, _, retry = await stream(client, f"/projects/{workspace_id}/architecture")
    assert retry[-1]["type"] == "architecture_ready"


async def test_redesign_and_approval(client: AsyncClient):
    workspace_id, _ = await designed_project(client)
    status, _, events = await stream(client, f"/projects/{workspace_id}/architecture/redesign", {"preference": "simpler"})
    assert status == 200 and events[-1]["data"]["technical_plan"]["plan"]["redesigns_used"] == 1
    assert (await stream(client, f"/projects/{workspace_id}/architecture/redesign", {"preference": "bigger"}))[0] == 422
    plan_id = events[-1]["data"]["technical_plan"]["plan"]["id"]
    assert (await client.post(f"/projects/{workspace_id}/architecture/approve", json={"plan_id": "x"})).status_code == 409
    response = await client.post(f"/projects/{workspace_id}/architecture/approve", json={"plan_id": plan_id})
    assert response.status_code == 200 and response.json()["stage"] == "TECHNICAL_PLAN_APPROVED"
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "TECHNICAL_PLAN_APPROVED" and brain["technical_plan"]["status"] == "approved"
    body = (await client.get(f"/projects/{workspace_id}/architecture")).json()
    assert body["technical_plan"]["can_redesign"] is False and body["latest_run"]["status"] == "complete"
    assert (await client.get("/projects/nope/architecture")).status_code == 404
