"""
Integration tests for the supervisor readiness routes (Release 0.13, Step 4).
"""
from httpx import AsyncClient

from tests.integration.test_feasibility_api import assessed_project, plan_approved_project
from tests.integration.test_fyp_design_api import stream

TYPES = ["supervisor_brief_started"] + ["supervisor_brief_progress"] * 4 + ["supervisor_readiness_ready"]


async def feasibility_accepted_project(client: AsyncClient) -> str:
    workspace_id, ready = await assessed_project(client)
    response = await client.post(f"/projects/{workspace_id}/feasibility/accept",
                                 json={"report_id": ready["data"]["feasibility"]["report"]["id"]})
    assert response.status_code == 200 and response.json()["allowed_actions"] == ["prepareSupervisorBrief"]
    return workspace_id


async def briefed_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await feasibility_accepted_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/supervisor-brief")
    return workspace_id, events[-1]


async def test_the_brief_streams_events_in_order(client: AsyncClient):
    workspace_id = await feasibility_accepted_project(client)
    status, content_type, events = await stream(client, f"/projects/{workspace_id}/supervisor-brief")
    assert status == 200 and content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == TYPES
    ready = events[-1]
    assert ready["stage"] == "SUPERVISOR_READINESS" and ready["allowed_actions"] == ["confirmSupervisorReady"]
    assert len(ready["data"]["supervisor_brief"]["brief"]["brief"]["questions"]) == 10


async def test_brief_errors(client: AsyncClient):
    workspace_id = await plan_approved_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/supervisor-brief"))[0] == 409
    assert (await stream(client, "/projects/nope/supervisor-brief"))[0] == 404
    workspace_id, _ = await briefed_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/supervisor-brief"))[0] == 409


async def test_confirmation_ends_release_0_13(client: AsyncClient):
    workspace_id, ready = await briefed_project(client)
    brief_id = ready["data"]["supervisor_brief"]["brief"]["id"]
    assert (await client.post(f"/projects/{workspace_id}/supervisor-brief/confirm", json={"brief_id": "x"})).status_code == 409
    response = await client.post(f"/projects/{workspace_id}/supervisor-brief/confirm", json={"brief_id": brief_id})
    assert response.status_code == 200 and response.json()["stage"] == "SUPERVISOR_READY"
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "SUPERVISOR_READY" and brain["supervisor_brief"]["status"] == "confirmed"
    body = (await client.get(f"/projects/{workspace_id}/supervisor-brief")).json()
    assert body["supervisor_brief"]["brief"]["status"] == "confirmed" and body["latest_run"]["status"] == "complete"
    assert (await client.get("/projects/nope/supervisor-brief")).status_code == 404
