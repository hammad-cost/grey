"""
Integration tests for the AI necessity check and AI strategy API (Release 0.7, Step 4).

  POST /projects/{id}/ai-strategy           — streams GreyEvents as newline-delimited JSON
  POST /projects/{id}/ai-strategy/recheck   — streams a re-check with the student's preference
  POST /projects/{id}/ai-strategy/approve   — the student's approval (HITL resume)
  GET  /projects/{id}/ai-strategy           — the strategy and the latest attempt

Uses the shared `client` fixture from conftest.py (in-memory database, fresh
workflow graphs, mock search, fake-mode LLM — never a real model).
"""
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.ai_strategy import get_ai_strategy_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.ai_strategy import build_ai_strategy_graph
from app.domains.fyp.workflows.ai_strategy.events import FAILED_MESSAGE
from main import app
from tests.integration.test_fyp_design_api import stream
from tests.integration.test_project_definition_api import defined_project
from tests.unit.test_plan_ai_strategy_skill import GOOD_STRATEGY

CHECK_TYPES = [
    "ai_strategy_started",
    "ai_strategy_progress",
    "ai_strategy_progress",
    "ai_strategy_progress",
    "ai_strategy_ready",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def scope_approved_project(client: AsyncClient) -> str:
    workspace_id, definition = await defined_project(client)
    response = await client.post(f"/projects/{workspace_id}/scope/approve", json={"definition_id": definition["id"]})
    assert response.status_code == 200
    return workspace_id


def use_llm_answers(answers: list):
    """Swap the AI strategy graph for one whose (fake) model gives these answers first."""
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", answers)
    graph = build_ai_strategy_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_ai_strategy_graph] = lambda: graph


async def checked_project(client: AsyncClient) -> tuple[str, dict]:
    """A project with an AI strategy to review (Grey says traditional ML). Returns (id, the ready event)."""
    workspace_id = await scope_approved_project(client)
    use_llm_answers([GOOD_STRATEGY])
    _, _, events = await stream(client, f"/projects/{workspace_id}/ai-strategy")
    return workspace_id, events[-1]


# ── POST /projects/{id}/ai-strategy ───────────────────────────────────────────

async def test_the_check_streams_events_in_order(client: AsyncClient):
    workspace_id = await scope_approved_project(client)

    status, content_type, events = await stream(client, f"/projects/{workspace_id}/ai-strategy")

    assert status == 200
    assert content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == CHECK_TYPES
    ready = events[-1]
    assert ready["stage"] == "AI_STRATEGY"
    assert ready["status"] == "awaiting_user"
    assert "approveAIStrategy" in ready["allowed_actions"]
    assert ready["data"]["ai_strategy"]["strategy"]["status"] == "draft"
    assert ready["brain_patch"]["workflow_state"] == "AI_STRATEGY"


async def test_the_check_needs_an_approved_scope(client: AsyncClient):
    workspace_id, _ = await defined_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/ai-strategy")
    assert status == 409

    status, _, _ = await stream(client, "/projects/nope/ai-strategy")
    assert status == 404


async def test_the_check_runs_once(client: AsyncClient):
    workspace_id, _ = await checked_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/ai-strategy")
    assert status == 409


async def test_a_failure_is_safe_and_can_be_retried(client: AsyncClient):
    workspace_id = await scope_approved_project(client)
    use_llm_answers([LLMUnavailable("vendor outage (internal detail)")])

    _, _, events = await stream(client, f"/projects/{workspace_id}/ai-strategy")

    failed = events[-1]
    assert failed["type"] == "ai_strategy_failed"
    assert failed["allowed_actions"] == ["checkAINeed"]
    assert failed["data"]["message"] == FAILED_MESSAGE
    assert "internal detail" not in str(events)

    _, _, retry = await stream(client, f"/projects/{workspace_id}/ai-strategy")
    assert retry[-1]["type"] == "ai_strategy_ready"


# ── POST /projects/{id}/ai-strategy/recheck ───────────────────────────────────

async def test_a_recheck_streams_and_follows_the_preference(client: AsyncClient):
    workspace_id, ready = await checked_project(client)
    assert ready["allowed_actions"] == ["approveAIStrategy", "recheckAIStrategy"]

    status, _, events = await stream(
        client, f"/projects/{workspace_id}/ai-strategy/recheck", {"preference": "without_ai"}
    )

    assert status == 200
    assert [e["type"] for e in events] == CHECK_TYPES
    view = events[-1]["data"]["ai_strategy"]
    assert view["strategy"]["strategy"]["necessity"] == "rule_based"
    assert view["strategy"]["rechecks_used"] == 1
    assert view["uses_ai"] is False
    assert events[-1]["allowed_actions"] == ["approveAIStrategy"]


async def test_a_recheck_that_makes_no_sense_is_refused(client: AsyncClient):
    workspace_id, _ = await checked_project(client)
    await stream(client, f"/projects/{workspace_id}/ai-strategy/recheck", {"preference": "without_ai"})

    status, _, _ = await stream(client, f"/projects/{workspace_id}/ai-strategy/recheck", {"preference": "without_ai"})
    assert status == 409                                     # it already works without AI


async def test_a_recheck_needs_a_known_preference(client: AsyncClient):
    workspace_id, _ = await checked_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/ai-strategy/recheck", {"preference": "more_ai"})
    assert status == 422                                     # Grey never offers "more AI"


async def test_a_recheck_needs_a_strategy(client: AsyncClient):
    workspace_id = await scope_approved_project(client)
    status, _, _ = await stream(client, f"/projects/{workspace_id}/ai-strategy/recheck", {"preference": "without_ai"})
    assert status == 409


# ── POST /projects/{id}/ai-strategy/approve ───────────────────────────────────

async def test_approval_ends_release_0_7(client: AsyncClient):
    workspace_id, ready = await checked_project(client)
    strategy_id = ready["data"]["ai_strategy"]["strategy"]["id"]

    response = await client.post(f"/projects/{workspace_id}/ai-strategy/approve", json={"strategy_id": strategy_id})

    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "ai_strategy_approved"
    assert event["stage"] == "AI_STRATEGY_APPROVED"
    assert event["status"] == "complete"
    assert event["allowed_actions"] == ["findDatasets"]          # Release 0.8: datasets come next
    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert brain["workflow_state"] == "AI_STRATEGY_APPROVED"
    assert brain["ai_strategy"]["status"] == "approved"


async def test_approval_errors(client: AsyncClient):
    workspace_id, ready = await checked_project(client)
    response = await client.post(f"/projects/{workspace_id}/ai-strategy/approve", json={"strategy_id": "nope"})
    assert response.status_code == 409
    response = await client.post("/projects/nope/ai-strategy/approve", json={"strategy_id": "x"})
    assert response.status_code == 404

    strategy_id = ready["data"]["ai_strategy"]["strategy"]["id"]
    await client.post(f"/projects/{workspace_id}/ai-strategy/approve", json={"strategy_id": strategy_id})
    response = await client.post(f"/projects/{workspace_id}/ai-strategy/approve", json={"strategy_id": strategy_id})
    assert response.status_code == 409                       # already approved
    status, _, _ = await stream(client, f"/projects/{workspace_id}/ai-strategy/recheck", {"preference": "without_ai"})
    assert status == 409                                     # nothing changes after approval


# ── GET /projects/{id}/ai-strategy ────────────────────────────────────────────

async def test_get_returns_the_strategy_and_latest_run(client: AsyncClient):
    workspace_id, _ = await checked_project(client)

    response = await client.get(f"/projects/{workspace_id}/ai-strategy")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_state"] == "AI_STRATEGY"
    assert body["ai_strategy"]["strategy"]["strategy"]["necessity"] == "traditional_ml"
    assert body["ai_strategy"]["core_features"]
    assert body["latest_run"]["status"] == "complete"


async def test_get_before_the_scope_is_approved(client: AsyncClient):
    workspace_id, _ = await defined_project(client)
    body = (await client.get(f"/projects/{workspace_id}/ai-strategy")).json()
    assert body["ai_strategy"] is None and body["latest_run"] is None

    response = await client.get("/projects/nope/ai-strategy")
    assert response.status_code == 404
