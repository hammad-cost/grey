"""
Integration tests for the Problem API (Release 0.3).

  POST /projects/{id}/problems — streams GreyEvents as newline-delimited JSON
  POST /projects/{id}/problem  — the student's choice (HITL resume)
  GET  /projects/{id}/problems — current options and the choice

Uses the shared `client` fixture from conftest.py (in-memory database, fresh
workflow graph, mock search, fake-mode LLM — never a real model).
"""
import json

from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.projects import get_discovery_graph
from app.core.config.settings import Settings
from app.core.llm import LLMUnavailable, build_llm_gateway
from app.core.skills.registry import SkillRegistry
from app.core.tools.providers.mock_search import MockSearchProvider
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import build_discovery_graph, problem_runner
from app.domains.fyp.workflows.discovery.problem_events import FAILED_MESSAGE
from main import app
from tests.integration.test_research_api import project_with_branch, run_research

EXPECTED_TYPES = [
    "problem_extraction_started",
    "problem_extraction_progress",      # reviewing evidence
    "problem_extraction_progress",      # identifying problems
    "problem_extraction_progress",      # checking problems
    "problem_extraction_progress",      # saving
    "problem_options_ready",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def find_problems(client: AsyncClient, workspace_id: str) -> tuple[int, str, list[dict]]:
    """POST the problems route and return (status code, content type, parsed events)."""
    response = await client.post(f"/projects/{workspace_id}/problems")
    lines = [line for line in response.text.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines] if response.status_code == 200 else []
    return response.status_code, response.headers.get("content-type", ""), events


async def researched_project(client: AsyncClient, industry="Defense", branch="Navy") -> str:
    workspace_id = await project_with_branch(client, industry, branch)
    _, _, events = await run_research(client, workspace_id)
    assert events[-1]["type"] == "research_completed"
    return workspace_id


async def project_with_options(client: AsyncClient) -> tuple[str, list[dict]]:
    workspace_id = await researched_project(client)
    _, _, events = await find_problems(client, workspace_id)
    return workspace_id, events[-1]["data"]["problems"]


def use_failing_llm():
    """Swap the test graph for one whose (fake) model is unavailable on the first call."""
    gateway = build_llm_gateway(Settings(_env_file=None, llm_mode="fake"))
    skills = SkillRegistry()
    register_fyp_skills(skills, MockSearchProvider(), gateway)
    gateway.router.provider("fake").script("fake-model", [LLMUnavailable("vendor outage (internal detail)")])
    graph = build_discovery_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_discovery_graph] = lambda: graph


# ── POST /projects/{id}/problems ──────────────────────────────────────────────

async def test_research_completed_tells_the_frontend_to_find_problems(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    _, _, events = await run_research(client, workspace_id)
    assert events[-1]["allowed_actions"] == ["extractProblems"]


async def test_problems_stream_events_in_order(client: AsyncClient):
    workspace_id = await researched_project(client)

    status, content_type, events = await find_problems(client, workspace_id)

    assert status == 200
    assert content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == EXPECTED_TYPES


async def test_options_ready_event_has_three_to_five_cards_with_sources(client: AsyncClient):
    workspace_id = await researched_project(client)
    _, _, events = await find_problems(client, workspace_id)
    ready = events[-1]

    assert ready["stage"] == "PROBLEM_OPTIONS"
    assert ready["status"] == "awaiting_user"
    assert ready["allowed_actions"] == ["selectProblem"]
    problems = ready["data"]["problems"]
    assert 3 <= len(problems) <= 5
    for problem in problems:
        for field in ("id", "title", "real_world_problem", "observed_solutions", "technical_problem",
                      "task_type", "why_it_matters", "possible_fyp_direction"):
            assert problem[field]
        assert problem["evidence"], "every problem cites at least one source"
        for source in problem["evidence"]:
            assert source["url"].startswith("https://") and source["title"] and source["supporting_point"]


async def test_problems_unknown_project_returns_404(client: AsyncClient):
    response = await client.post("/projects/does-not-exist/problems")
    assert response.status_code == 404


async def test_problems_before_research_returns_409(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    response = await client.post(f"/projects/{workspace_id}/problems")
    assert response.status_code == 409


async def test_problems_already_running_returns_409(client: AsyncClient):
    workspace_id = await researched_project(client)
    problem_runner._active_extractions.add(workspace_id)     # pretend a run is in progress

    response = await client.post(f"/projects/{workspace_id}/problems")
    assert response.status_code == 409


async def test_problems_again_after_options_exist_returns_409(client: AsyncClient):
    workspace_id, _ = await project_with_options(client)
    response = await client.post(f"/projects/{workspace_id}/problems")
    assert response.status_code == 409


async def test_research_again_after_options_exist_returns_409(client: AsyncClient):
    workspace_id, _ = await project_with_options(client)
    response = await client.post(f"/projects/{workspace_id}/research")
    assert response.status_code == 409


async def test_llm_failure_streams_a_safe_failed_event_and_can_be_retried(client: AsyncClient):
    workspace_id = await researched_project(client)
    use_failing_llm()

    status, _, events = await find_problems(client, workspace_id)

    assert status == 200
    failed = events[-1]
    assert failed["type"] == "problem_extraction_failed"
    assert failed["status"] == "blocked"
    assert failed["allowed_actions"] == ["extractProblems"]
    assert failed["data"]["message"] == FAILED_MESSAGE
    assert "internal detail" not in json.dumps(events)

    # The scripted outage is used up; trying again succeeds.
    _, _, retry = await find_problems(client, workspace_id)
    assert retry[-1]["type"] == "problem_options_ready"


# ── GET /projects/{id}/problems ───────────────────────────────────────────────

async def test_no_problems_before_extraction(client: AsyncClient):
    workspace_id = await researched_project(client)

    response = await client.get(f"/projects/{workspace_id}/problems")

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": workspace_id, "problem_run": None, "problems": [], "selected_problem_id": None,
    }


async def test_get_problems_after_extraction_matches_the_stream(client: AsyncClient):
    workspace_id, streamed = await project_with_options(client)

    body = (await client.get(f"/projects/{workspace_id}/problems")).json()

    assert body["problem_run"]["status"] == "complete"
    assert body["problem_run"]["provider"] == "fake"
    assert [p["id"] for p in body["problems"]] == [p["id"] for p in streamed]
    assert [p["rank"] for p in body["problems"]] == list(range(1, len(streamed) + 1))
    assert body["selected_problem_id"] is None


async def test_get_problems_unknown_project_returns_404(client: AsyncClient):
    response = await client.get("/projects/does-not-exist/problems")
    assert response.status_code == 404


# ── POST /projects/{id}/problem ───────────────────────────────────────────────

async def test_select_problem(client: AsyncClient):
    workspace_id, problems = await project_with_options(client)
    chosen = problems[1]

    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": chosen["id"]})

    assert response.status_code == 200
    event = response.json()
    assert event["type"] == "problem_selected"
    assert event["stage"] == "PROBLEM_SELECTED"
    assert event["status"] == "complete"
    assert event["allowed_actions"] == ["designFYP"]      # Release 0.5: the FYP design comes next
    assert event["data"]["problem"]["id"] == chosen["id"]
    assert event["brain_patch"]["selected_problem_title"] == chosen["title"]

    listing = (await client.get(f"/projects/{workspace_id}/problems")).json()
    assert listing["selected_problem_id"] == chosen["id"]
    snapshot = (await client.get(f"/projects/{workspace_id}")).json()
    assert snapshot["workflow_state"] == "PROBLEM_SELECTED"
    assert snapshot["selected_problem"]["id"] == chosen["id"]


async def test_select_unknown_problem_returns_409(client: AsyncClient):
    workspace_id, _ = await project_with_options(client)
    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": "invented"})
    assert response.status_code == 409
    assert (await client.get(f"/projects/{workspace_id}")).json()["workflow_state"] == "PROBLEM_OPTIONS"


async def test_select_before_options_returns_409(client: AsyncClient):
    workspace_id = await researched_project(client)
    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": "anything"})
    assert response.status_code == 409


async def test_select_twice_returns_409(client: AsyncClient):
    workspace_id, problems = await project_with_options(client)
    await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": problems[0]["id"]})

    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": problems[1]["id"]})
    assert response.status_code == 409


async def test_select_problem_unknown_project_returns_404(client: AsyncClient):
    response = await client.post("/projects/does-not-exist/problem", json={"problem_id": "x"})
    assert response.status_code == 404


async def test_select_problem_needs_a_problem_id(client: AsyncClient):
    workspace_id, _ = await project_with_options(client)
    assert (await client.post(f"/projects/{workspace_id}/problem", json={})).status_code == 422
    assert (await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": ""})).status_code == 422


# ── Whole journey over HTTP ───────────────────────────────────────────────────

async def test_full_release_03_journey(client: AsyncClient):
    """Start → industry → branch → research → problems → choice, through the real HTTP API."""
    workspace_id = await researched_project(client, "Finance", "Fraud Detection")
    _, _, events = await find_problems(client, workspace_id)
    problems = events[-1]["data"]["problems"]

    response = await client.post(f"/projects/{workspace_id}/problem", json={"problem_id": problems[0]["id"]})
    assert response.status_code == 200

    brain = (await client.get(f"/projects/{workspace_id}")).json()
    assert (brain["industry"], brain["branch"]) == ("Finance", "Fraud Detection")
    assert brain["research"]["status"] == "complete"
    assert brain["problem_run"]["status"] == "complete"
    assert brain["workflow_state"] == "PROBLEM_SELECTED"
    assert brain["selected_problem"]["title"] == problems[0]["title"]
