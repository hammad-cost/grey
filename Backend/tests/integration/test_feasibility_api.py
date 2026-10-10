"""
Integration tests for the feasibility routes (Release 0.12, Step 4).
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.feasibility import get_feasibility_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.feasibility import build_feasibility_graph
from main import app
from tests.integration.test_architecture_api import designed_project, technology_approved_project
from tests.integration.test_fyp_design_api import stream

TYPES = ["feasibility_started"] + ["feasibility_progress"] * 4 + ["feasibility_ready"]


async def plan_approved_project(client: AsyncClient) -> str:
    workspace_id, ready = await designed_project(client)
    response = await client.post(f"/projects/{workspace_id}/architecture/approve",
                                 json={"plan_id": ready["data"]["technical_plan"]["plan"]["id"]})
    assert response.status_code == 200 and response.json()["allowed_actions"] == ["assessFeasibility"]
    return workspace_id


async def assessed_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await plan_approved_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/feasibility")
    return workspace_id, events[-1]


async def test_the_check_streams_events_in_order(client: AsyncClient):
    workspace_id = await plan_approved_project(client)
    status, content_type, events = await stream(client, f"/projects/{workspace_id}/feasibility")
    assert status == 200 and content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == TYPES
    ready = events[-1]
    assert ready["stage"] == "FEASIBILITY" and ready["allowed_actions"] == ["acceptFeasibility"]
    assert len(ready["data"]["feasibility"]["report"]["report"]["dimensions"]) == 13


async def test_check_errors_and_failures(client: AsyncClient):
    workspace_id = await technology_approved_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/feasibility"))[0] == 409
    assert (await stream(client, "/projects/nope/feasibility"))[0] == 404

    workspace_id = await plan_approved_project(client)
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    graph = build_feasibility_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_feasibility_graph] = lambda: graph
    _, _, events = await stream(client, f"/projects/{workspace_id}/feasibility")
    assert events[-1]["type"] == "feasibility_failed" and events[-1]["allowed_actions"] == ["assessFeasibility"]
    assert "internal detail" not in str(events)
    _, _, retry = await stream(client, f"/projects/{workspace_id}/feasibility")
    assert retry[-1]["type"] == "feasibility_ready"
    assert (await stream(client, f"/projects/{workspace_id}/feasibility"))[0] == 409


async def test_acceptance_ends_release_0_12(client: AsyncClient):
    workspace_id, ready = await assessed_project(client)
    report_id = ready["data"]["feasibility"]["report"]["id"]
    assert (await client.post(f"/projects/{workspace_id}/feasibility/accept", json={"report_id": "x"})).status_code == 409
    response = await client.post(f"/projects/{workspace_id}/feasibility/accept", json={"report_id": report_id})
    assert response.status_code == 200 and response.json()["stage"] == "FEASIBILITY_ACCEPTED"
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "FEASIBILITY_ACCEPTED" and brain["feasibility_report"]["status"] == "accepted"
    body = (await client.get(f"/projects/{workspace_id}/feasibility")).json()
    assert body["feasibility"]["report"]["status"] == "accepted" and body["latest_run"]["status"] == "complete"
    assert (await client.get("/projects/nope/feasibility")).status_code == 404
