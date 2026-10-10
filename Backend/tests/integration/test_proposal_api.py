"""
Integration tests for the proposal routes (Release 0.14, Step 4) — the end of the journey.
"""
from httpx import AsyncClient

from tests.integration.test_fyp_design_api import stream
from tests.integration.test_supervisor_api import briefed_project, feasibility_accepted_project


async def ready_project(client: AsyncClient) -> str:
    workspace_id, ready = await briefed_project(client)
    response = await client.post(f"/projects/{workspace_id}/supervisor-brief/confirm",
                                 json={"brief_id": ready["data"]["supervisor_brief"]["brief"]["id"]})
    assert response.status_code == 200 and response.json()["allowed_actions"] == ["generateProposal"]
    return workspace_id


async def written_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await ready_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/proposal")
    return workspace_id, events[-1]


async def test_writing_streams_events_in_order(client: AsyncClient):
    workspace_id = await ready_project(client)
    status, content_type, events = await stream(client, f"/projects/{workspace_id}/proposal")
    assert status == 200 and content_type.startswith("application/x-ndjson")
    assert events[0]["type"] == "proposal_started" and events[-1]["type"] == "proposal_ready"
    ready = events[-1]
    assert ready["stage"] == "PROPOSAL_GENERATION"
    assert ready["allowed_actions"] == ["finalizeProposal", "rewriteProposalSection"]
    assert len(ready["data"]["proposal"]["proposal"]["proposal"]["sections"]) == 23


async def test_writing_errors(client: AsyncClient):
    workspace_id = await feasibility_accepted_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/proposal"))[0] == 409
    assert (await stream(client, "/projects/nope/proposal"))[0] == 404
    assert (await client.get(f"/projects/{workspace_id}/proposal/markdown")).status_code == 404
    workspace_id, _ = await written_project(client)
    assert (await stream(client, f"/projects/{workspace_id}/proposal"))[0] == 409


async def test_rewrite_download_and_finalize(client: AsyncClient):
    workspace_id, ready = await written_project(client)
    status, _, events = await stream(client, f"/projects/{workspace_id}/proposal/rewrite", {"section": "introduction"})
    assert status == 200 and events[-1]["data"]["proposal"]["proposal"]["rewrites_used"] == 1
    assert (await stream(client, f"/projects/{workspace_id}/proposal/rewrite", {"section": "dataset"}))[0] == 409
    assert (await stream(client, f"/projects/{workspace_id}/proposal/rewrite", {"section": "conclusion"}))[0] == 422

    download = await client.get(f"/projects/{workspace_id}/proposal/markdown")
    assert download.status_code == 200 and download.headers["content-type"].startswith("text/markdown")
    assert "fyp-proposal.md" in download.headers["content-disposition"]
    assert download.text.startswith("# ") and "## References" in download.text

    proposal_id = ready["data"]["proposal"]["proposal"]["id"]
    assert (await client.post(f"/projects/{workspace_id}/proposal/finalize", json={"proposal_id": "x"})).status_code == 409
    response = await client.post(f"/projects/{workspace_id}/proposal/finalize", json={"proposal_id": proposal_id})
    assert response.status_code == 200 and response.json()["stage"] == "COMPLETE"
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "COMPLETE" and brain["proposal"]["status"] == "final"
    body = (await client.get(f"/projects/{workspace_id}/proposal")).json()
    assert body["proposal"]["rewritable_sections"] == [] and body["latest_run"]["status"] == "complete"
    assert (await client.get("/projects/nope/proposal")).status_code == 404
