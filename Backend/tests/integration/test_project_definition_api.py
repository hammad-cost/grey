"""
Integration tests for the project definition and scope API (Release 0.6, Step 4).

  POST /projects/{id}/project-definition  — streams GreyEvents as newline-delimited JSON
  POST /projects/{id}/scope/move          — move one feature (HITL resume)
  POST /projects/{id}/scope/approve       — the student's approval (HITL resume)
  GET  /projects/{id}/project-definition  — the definition, scope and latest attempt

Uses the shared `client` fixture from conftest.py (in-memory database, fresh
workflow graphs, mock search, fake-mode LLM — never a real model).
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.project_definition import get_project_definition_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.project_definition import build_project_definition_graph
from app.domains.fyp.workflows.project_definition.events import FAILED_MESSAGE
from main import app
from tests.integration.test_fyp_design_api import designed_project, stream

DEFINITION_TYPES = [
    "project_definition_started",
    "project_definition_progress",
    "project_definition_progress",
    "project_definition_progress",
    "project_definition_ready",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def approved_project(client: AsyncClient) -> str:
    workspace_id, ready = await designed_project(client)
    design_id = ready["data"]["fyp"]["design"]["id"]
    response = await client.post(f"/projects/{workspace_id}/fyp-design/approve", json={"design_id": design_id})
    assert response.status_code == 200
    return workspace_id


async def defined_project(client: AsyncClient) -> tuple[str, dict]:
    """A project whose definition is ready for review. Returns (id, the stored definition)."""
    workspace_id = await approved_project(client)
    _, _, events = await stream(client, f"/projects/{workspace_id}/project-definition")
    return workspace_id, events[-1]["data"]["definition"]["definition"]


def items(definition: dict, kind: str) -> list[dict]:
    return [item for item in definition["scope"] if item["kind"] == kind]


def use_failing_llm():
    """Swap the definition graph for one whose (fake) model is unavailable on the first call."""
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    graph = build_project_definition_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_project_definition_graph] = lambda: graph


# ── POST /projects/{id}/project-definition ────────────────────────────────────

async def test_definition_streams_events_in_order(client: AsyncClient):
    workspace_id = await approved_project(client)

    status, content_type, events = await stream(client, f"/projects/{workspace_id}/project-definition")

    assert status == 200
    assert content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == DEFINITION_TYPES
    ready = events[-1]
    assert ready["stage"] == "SCOPE"
    assert ready["status"] == "awaiting_user"
    assert ready["allowed_actions"] == ["approveScope", "modifyScope"]
    view = ready["data"]["definition"]
    assert view["fyp_title"] and view["target_user"]
    assert len(items(view["definition"], "core")) == 3
    assert view["min_core_features"] == 2 and view["max_core_features"] == 8


async def test_definition_errors_before_streaming(client: AsyncClient):
    assert (await client.post("/projects/nope/project-definition")).status_code == 404

    workspace_id, _ = await designed_project(client)              # designed, not approved
    assert (await client.post(f"/projects/{workspace_id}/project-definition")).status_code == 409


async def test_definition_cannot_run_twice(client: AsyncClient):
    workspace_id, _ = await defined_project(client)
    assert (await client.post(f"/projects/{workspace_id}/project-definition")).status_code == 409


async def test_a_failed_definition_sends_a_safe_event_and_can_be_retried(client: AsyncClient):
    workspace_id = await approved_project(client)
    use_failing_llm()

    status, _, events = await stream(client, f"/projects/{workspace_id}/project-definition")

    assert status == 200
    failed = events[-1]
    assert failed["type"] == "project_definition_failed"
    assert failed["allowed_actions"] == ["defineProject"]
    assert failed["data"]["message"] == FAILED_MESSAGE
    assert "internal detail" not in str(events)

    _, _, retry = await stream(client, f"/projects/{workspace_id}/project-definition")
    assert retry[-1]["type"] == "project_definition_ready"


# ── POST /projects/{id}/scope/move ────────────────────────────────────────────

async def test_move_a_feature(client: AsyncClient):
    workspace_id, definition = await defined_project(client)
    feature = items(definition, "optional")[0]

    response = await client.post(f"/projects/{workspace_id}/scope/move", json={"item_id": feature["id"], "to": "core"})

    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "scope_updated"
    assert event["allowed_actions"] == ["approveScope", "modifyScope"]
    assert items(event["data"]["definition"]["definition"], "core")[-1]["id"] == feature["id"]
    assert event["brain_patch"]["core_feature_count"] == 4


async def test_move_errors(client: AsyncClient):
    workspace_id, definition = await defined_project(client)
    path = f"/projects/{workspace_id}/scope/move"
    core = items(definition, "core")

    assert (await client.post("/projects/nope/scope/move", json={"item_id": "x", "to": "core"})).status_code == 404
    assert (await client.post(path, json={"item_id": core[0]["id"], "to": "somewhere"})).status_code == 422
    assert (await client.post(path, json={"item_id": "unknown", "to": "core"})).status_code == 409
    assert (await client.post(path, json={"item_id": core[0]["id"], "to": "core"})).status_code == 409

    assert (await client.post(path, json={"item_id": core[0]["id"], "to": "optional"})).status_code == 200
    too_few = await client.post(path, json={"item_id": core[1]["id"], "to": "optional"})
    assert too_few.status_code == 409
    assert "at least 2" in too_few.json()["detail"]


# ── POST /projects/{id}/scope/approve ─────────────────────────────────────────

async def test_approve_ends_release_0_6(client: AsyncClient):
    workspace_id, definition = await defined_project(client)

    response = await client.post(f"/projects/{workspace_id}/scope/approve", json={"definition_id": definition["id"]})

    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "scope_approved"
    assert event["stage"] == "SCOPE_APPROVED"
    assert event["allowed_actions"] == []
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "SCOPE_APPROVED"
    assert brain["project_definition"]["status"] == "approved"


async def test_approve_errors(client: AsyncClient):
    workspace_id, definition = await defined_project(client)
    path = f"/projects/{workspace_id}/scope/approve"

    assert (await client.post("/projects/nope/scope/approve", json={"definition_id": "x"})).status_code == 404
    assert (await client.post(path, json={"definition_id": "wrong"})).status_code == 409
    assert (await client.post(path, json={})).status_code == 422
    assert (await client.post(path, json={"definition_id": definition["id"]})).status_code == 200
    assert (await client.post(path, json={"definition_id": definition["id"]})).status_code == 409   # already approved
    moved = await client.post(f"/projects/{workspace_id}/scope/move",
                              json={"item_id": definition["scope"][0]["id"], "to": "optional"})
    assert moved.status_code == 409                                                               # locked after approval


# ── GET /projects/{id}/project-definition ─────────────────────────────────────

async def test_get_definition(client: AsyncClient):
    assert (await client.get("/projects/nope/project-definition")).status_code == 404

    workspace_id, _ = await designed_project(client)
    before = (await client.get(f"/projects/{workspace_id}/project-definition")).json()
    assert before["definition"] is None and before["latest_run"] is None      # FYP not approved yet

    workspace_id, definition = await defined_project(client)
    body = (await client.get(f"/projects/{workspace_id}/project-definition")).json()
    assert body["workflow_state"] == "SCOPE"
    assert body["definition"]["definition"]["id"] == definition["id"]
    assert body["latest_run"]["status"] == "complete"
