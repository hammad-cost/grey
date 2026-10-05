"""
Integration tests for the Research API (Release 0.2).

  POST /projects/{id}/research — streams GreyEvents as newline-delimited JSON
  GET  /projects/{id}/evidence — evidence saved in the Project Brain

Uses the shared `client` fixture from conftest.py (in-memory database,
fresh workflow graph, mock search provider with no delay).
"""
import json

from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.projects import get_discovery_graph
from app.core.events import GreyEvent
from app.core.skills.registry import SkillRegistry, skill_registry
from app.core.tools.search import SearchProvider, SearchProviderError, SearchQuery
from app.domains.fyp.skills import register_fyp_skills
from app.domains.fyp.workflows.discovery import build_discovery_graph
from app.domains.fyp.workflows.discovery import research_runner
from app.domains.fyp.workflows.discovery.research_events import FAILED_MESSAGE
from main import app, register_skills

EXPECTED_TYPES = [
    "research_started",
    "searching_sources", "sources_found",     # discover startups
    "searching_sources", "sources_found",     # confirm on startup websites
    "searching_sources", "sources_found",     # industry news
    "searching_sources", "sources_found",     # government
    "searching_sources", "sources_found",     # research papers
    "searching_sources", "sources_found",     # datasets
    "evaluating_evidence",
    "storing_evidence",
    "research_completed",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def project_with_branch(client: AsyncClient, industry="Defense", branch="Navy") -> str:
    """Create a project and choose an industry and branch. Returns the workspace id."""
    workspace_id = (await client.post("/projects")).json()["workspace_id"]
    await client.post(f"/projects/{workspace_id}/industry", json={"industry": industry})
    await client.post(f"/projects/{workspace_id}/branch", json={"branch": branch})
    return workspace_id


async def run_research(client: AsyncClient, workspace_id: str) -> tuple[int, str, list[dict]]:
    """POST the research route and return (status code, content type, parsed events)."""
    response = await client.post(f"/projects/{workspace_id}/research")
    lines = [line for line in response.text.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines] if response.status_code == 200 else []
    return response.status_code, response.headers.get("content-type", ""), events


class BrokenSearch(SearchProvider):
    """A provider that is always down."""
    name = "broken"

    async def search(self, query: SearchQuery):
        raise SearchProviderError("connection refused by search vendor (internal detail)")


def use_broken_search():
    """Swap the test graph for one whose search provider always fails."""
    skills = SkillRegistry()
    register_fyp_skills(skills, BrokenSearch())
    broken_graph = build_discovery_graph(MemorySaver(), skills=skills)
    app.dependency_overrides[get_discovery_graph] = lambda: broken_graph


# ── POST /projects/{id}/research ──────────────────────────────────────────────

async def test_research_streams_events_in_order(client: AsyncClient):
    workspace_id = await project_with_branch(client)

    status, content_type, events = await run_research(client, workspace_id)

    assert status == 200
    assert content_type.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == EXPECTED_TYPES


async def test_every_streamed_line_is_a_valid_grey_event(client: AsyncClient):
    workspace_id = await project_with_branch(client)

    _, _, events = await run_research(client, workspace_id)

    for event in events:
        parsed = GreyEvent.model_validate(event)
        assert parsed.workspace_id == workspace_id
        assert parsed.stage == "EVIDENCE_RESEARCH"
        assert parsed.data["industry"] == "Defense"
        assert parsed.data["branch"] == "Navy"


async def test_completed_event_has_summary_and_brain_patch(client: AsyncClient):
    workspace_id = await project_with_branch(client)

    _, _, events = await run_research(client, workspace_id)
    completed = events[-1]

    assert completed["status"] == "complete"
    assert completed["brain_patch"]["research_status"] == "complete"
    assert completed["data"]["summary"]["total_sources"] > 0
    assert completed["data"]["summary"]["provider"] == "mock"
    assert completed["brain_patch"]["evidence_count"] == completed["data"]["summary"]["total_sources"]


async def test_research_unknown_project_returns_404(client: AsyncClient):
    response = await client.post("/projects/does-not-exist/research")
    assert response.status_code == 404


async def test_research_before_branch_returns_409(client: AsyncClient):
    workspace_id = (await client.post("/projects")).json()["workspace_id"]
    await client.post(f"/projects/{workspace_id}/industry", json={"industry": "Defense"})

    response = await client.post(f"/projects/{workspace_id}/research")
    assert response.status_code == 409


async def test_research_already_running_returns_409(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    research_runner._active_research.add(workspace_id)   # pretend a run is in progress

    response = await client.post(f"/projects/{workspace_id}/research")
    assert response.status_code == 409


async def test_research_can_be_run_again(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    await run_research(client, workspace_id)

    status, _, events = await run_research(client, workspace_id)

    assert status == 200
    assert events[-1]["type"] == "research_completed"


async def test_provider_failure_streams_safe_failed_event(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    use_broken_search()

    status, _, events = await run_research(client, workspace_id)

    assert status == 200
    failed = events[-1]
    assert failed["type"] == "research_failed"
    assert failed["status"] == "blocked"
    assert failed["allowed_actions"] == ["startResearch"]
    assert failed["data"]["message"] == FAILED_MESSAGE
    # The internal error never reaches the browser.
    assert "internal detail" not in json.dumps(events)


# ── GET /projects/{id}/evidence ───────────────────────────────────────────────

async def test_evidence_is_empty_before_research(client: AsyncClient):
    workspace_id = await project_with_branch(client)

    response = await client.get(f"/projects/{workspace_id}/evidence")

    assert response.status_code == 200
    assert response.json() == {"workspace_id": workspace_id, "research": None, "evidence": []}


async def test_evidence_after_research(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    _, _, events = await run_research(client, workspace_id)
    total = events[-1]["data"]["summary"]["total_sources"]

    body = (await client.get(f"/projects/{workspace_id}/evidence")).json()

    assert body["research"]["status"] == "complete"
    assert body["research"]["sources_found"] == total
    assert len(body["evidence"]) == total

    # Strongest evidence first.
    tiers = [source["evidence_tier"] for source in body["evidence"]]
    assert tiers == sorted(tiers)

    # Every source has the transparency fields the blueprint requires.
    for source in body["evidence"]:
        for field in ("title", "organization", "source_type", "url",
                      "problem_addressed", "relevant_insight", "why_it_matters"):
            assert source[field]


async def test_evidence_after_failed_research_shows_failed_run(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    use_broken_search()
    await run_research(client, workspace_id)

    body = (await client.get(f"/projects/{workspace_id}/evidence")).json()

    assert body["research"]["status"] == "failed"
    assert body["evidence"] == []


async def test_evidence_unknown_project_returns_404(client: AsyncClient):
    response = await client.get("/projects/does-not-exist/evidence")
    assert response.status_code == 404


async def test_project_snapshot_includes_latest_research(client: AsyncClient):
    workspace_id = await project_with_branch(client)
    await run_research(client, workspace_id)

    snapshot = (await client.get(f"/projects/{workspace_id}")).json()

    assert snapshot["research"]["status"] == "complete"


# ── Startup registration ──────────────────────────────────────────────────────

def test_startup_registers_fyp_skills_once():
    register_skills()
    register_skills()   # calling twice must not raise "already registered"

    assert "research_evidence" in skill_registry
