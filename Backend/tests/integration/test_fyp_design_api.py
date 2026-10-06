"""
Integration tests for the FYP design API (Release 0.5, Step 4).

  POST /projects/{id}/fyp-design          — streams GreyEvents as newline-delimited JSON
  POST /projects/{id}/fyp-design/adjust   — one controlled redesign, streamed
  POST /projects/{id}/fyp-design/approve  — the student's approval (HITL resume)
  GET  /projects/{id}/fyp-design          — area, current design, "Why this FYP?"

Uses the shared `client` fixture from conftest.py (in-memory database, fresh
workflow graphs, mock search, fake-mode LLM — never a real model).
"""
import json

from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.fyp_design import get_fyp_design_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.fyp_design import build_fyp_design_graph
from app.domains.fyp.workflows.fyp_design.events import FAILED_MESSAGE
from main import app
from tests.integration.test_problems_api import project_with_options

FIRST_DESIGN_TYPES = [
    "fyp_design_started",
    "fyp_design_progress",
    "area_classified",
    "fyp_design_progress",
    "fyp_design_progress",
    "fyp_design_progress",
    "fyp_direction_ready",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def stream(client: AsyncClient, path: str, body: dict | None = None) -> tuple[int, str, list[dict]]:
    """POST a streaming route and return (status code, content type, parsed events)."""
    response = await client.post(path, json=body) if body is not None else await client.post(path)
    lines = [line for line in response.text.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines] if response.status_code == 200 else []
    return response.status_code, response.headers.get("content-type", ""), events


async def project_with_chosen_problem(client: AsyncClient) -> str:
    workspace_id, problems = await project_with_options(client)
    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": problems[0]["id"]})
    assert response.status_code == 200
    return workspace_id


async def designed_project(client: AsyncClient) -> tuple[str, dict]:
    workspace_id = await project_with_chosen_problem(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/fyp-design")
    return workspace_id, events[-1]


async def adjust(client: AsyncClient, workspace_id: str, adjustment="make_simpler", note=None):
    body = {"adjustment": adjustment} | ({"note": note} if note is not None else {})
    return await stream(client, f"/projects/{workspace_id}/fyp-design/adjust", body)


def use_failing_llm():
    """Swap the FYP graph for one whose (fake) model is unavailable on the first call."""
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    graph = build_fyp_design_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_fyp_design_graph] = lambda: graph


# ── POST /projects/{id}/fyp-design ────────────────────────────────────────────

async def test_choosing_a_problem_tells_the_frontend_to_design_the_fyp(client: AsyncClient):
    workspace_id, problems = await project_with_options(client)
    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": problems[0]["id"]})
    assert response.json()["allowed_actions"] == ["designFYP"]


async def test_design_streams_events_in_order(client: AsyncClient):
    workspace_id = await project_with_chosen_problem(client)

    status, content_type, events = await stream(client, f"/projects/{workspace_id}/fyp-design")

    assert status == 200
    assert content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == FIRST_DESIGN_TYPES
    ready = events[-1]
    assert ready["stage"] == "FYP_DESIGN"
    assert ready["status"] == "awaiting_user"
    assert ready["allowed_actions"] == ["approveFYPDirection", "adjustFYPDirection"]
    assert ready["data"]["fyp"]["area"]["functional_area"]
    assert ready["data"]["fyp"]["why_this_fyp"]["evidence"]


async def test_design_errors_before_streaming(client: AsyncClient):
    assert (await client.post("/projects/nope/fyp-design")).status_code == 404

    workspace_id, _ = await project_with_options(client)          # no problem chosen yet
    assert (await client.post(f"/projects/{workspace_id}/fyp-design")).status_code == 409


async def test_design_cannot_run_twice(client: AsyncClient):
    workspace_id, _ = await designed_project(client)
    assert (await client.post(f"/projects/{workspace_id}/fyp-design")).status_code == 409


async def test_a_failed_design_sends_a_safe_event_and_can_be_retried(client: AsyncClient):
    workspace_id = await project_with_chosen_problem(client)
    use_failing_llm()

    status, _, events = await stream(client, f"/projects/{workspace_id}/fyp-design")

    assert status == 200
    failed = events[-1]
    assert failed["type"] == "fyp_design_failed"
    assert failed["allowed_actions"] == ["designFYP"]
    assert failed["data"]["message"] == FAILED_MESSAGE
    assert "internal detail" not in json.dumps(events)

    _, _, events = await stream(client, f"/projects/{workspace_id}/fyp-design")
    assert events[-1]["type"] == "fyp_direction_ready"


# ── POST /projects/{id}/fyp-design/adjust ─────────────────────────────────────

async def test_adjust_streams_a_new_version(client: AsyncClient):
    workspace_id, _ = await designed_project(client)

    status, _, events = await adjust(client, workspace_id, "change_target_user", note="For port staff")

    assert status == 200
    assert events[-1]["type"] == "fyp_direction_ready"
    fyp = events[-1]["data"]["fyp"]
    assert fyp["design"]["version"] == 2
    assert (fyp["design"]["adjustment"], fyp["design"]["note"]) == ("change_target_user", "For port staff")
    assert fyp["adjustments_left"] == 2


async def test_adjust_only_accepts_controlled_options_and_short_notes(client: AsyncClient):
    workspace_id, _ = await designed_project(client)
    path = f"/projects/{workspace_id}/fyp-design/adjust"

    assert (await client.post(path, json={"adjustment": "more_ai"})).status_code == 422
    assert (await client.post(path, json={"adjustment": "make_simpler", "note": "x" * 201})).status_code == 422
    assert (await client.post(path, json={})).status_code == 422


async def test_adjust_stops_after_three_redesigns(client: AsyncClient):
    workspace_id, _ = await designed_project(client)
    for adjustment in ("make_simpler", "change_system_focus", "reduce_complexity"):
        _, _, events = await adjust(client, workspace_id, adjustment)

    assert events[-1]["allowed_actions"] == ["approveFYPDirection"]
    response = await client.post(f"/projects/{workspace_id}/fyp-design/adjust", json={"adjustment": "make_simpler"})
    assert response.status_code == 409


async def test_adjust_needs_a_design(client: AsyncClient):
    workspace_id = await project_with_chosen_problem(client)
    status, _, _ = await adjust(client, workspace_id)
    assert status == 409


# ── POST /projects/{id}/fyp-design/approve ────────────────────────────────────

async def test_approve_ends_release_0_5(client: AsyncClient):
    workspace_id, ready = await designed_project(client)
    design_id = ready["data"]["fyp"]["design"]["id"]

    response = await client.post(f"/projects/{workspace_id}/fyp-design/approve", json={"design_id": design_id})

    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "fyp_direction_approved"
    assert event["stage"] == "APPROVED_FYP"
    assert event["allowed_actions"] == []
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "APPROVED_FYP"
    assert brain["fyp_design"]["status"] == "approved"


async def test_approve_errors(client: AsyncClient):
    workspace_id, ready = await designed_project(client)
    path = f"/projects/{workspace_id}/fyp-design/approve"

    assert (await client.post("/projects/nope/fyp-design/approve", json={"design_id": "x"})).status_code == 404
    assert (await client.post(path, json={"design_id": "not-the-draft"})).status_code == 409
    assert (await client.post(path, json={})).status_code == 422

    design_id = ready["data"]["fyp"]["design"]["id"]
    assert (await client.post(path, json={"design_id": design_id})).status_code == 200
    assert (await client.post(path, json={"design_id": design_id})).status_code == 409     # already approved


# ── GET /projects/{id}/fyp-design ─────────────────────────────────────────────

async def test_get_returns_the_current_design_and_why(client: AsyncClient):
    workspace_id, _ = await designed_project(client)
    await adjust(client, workspace_id)

    response = await client.get(f"/projects/{workspace_id}/fyp-design")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_state"] == "FYP_DESIGN"
    assert body["fyp"]["design"]["version"] == 2
    assert body["fyp"]["adjustments_used"] == 1
    assert body["fyp"]["why_this_fyp"]["how_grey_made_it_student_sized"] == body["fyp"]["design"]["scope_reduction"]
    assert body["latest_run"]["kind"] == "adjustment"


async def test_get_before_a_problem_is_chosen(client: AsyncClient):
    workspace_id, _ = await project_with_options(client)
    body = (await client.get(f"/projects/{workspace_id}/fyp-design")).json()
    assert body["fyp"] is None and body["latest_run"] is None
    assert (await client.get("/projects/nope/fyp-design")).status_code == 404
