"""
Integration tests for the Projects API.

These tests run real HTTP requests against the FastAPI app using an
in-memory SQLite database and a fresh LangGraph MemorySaver per test.

This means:
  - No files are created on disk.
  - Each test is fully isolated — no data leaks between tests.
  - The full stack is exercised: route → workflow → repository → database.
"""
from httpx import AsyncClient

from app.core.brain.schemas import WorkflowState

# The `client` fixture lives in conftest.py (shared with test_research_api.py).


# ── Health check ──────────────────────────────────────────────────────────────

async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── CORS (browser frontend on another port) ───────────────────────────────────

async def test_cors_preflight_allows_frontend_origin(client: AsyncClient):
    """The browser asks permission before POSTing JSON from localhost:3000."""
    response = await client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_cors_rejects_unknown_origin(client: AsyncClient):
    """Origins not listed in CORS_ORIGINS get no permission header."""
    response = await client.options(
        "/projects",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers


# ── POST /projects ────────────────────────────────────────────────────────────

async def test_create_project_returns_201(client: AsyncClient):
    response = await client.post("/projects")
    assert response.status_code == 201


async def test_create_project_returns_correct_event(client: AsyncClient):
    response = await client.post("/projects")
    data = response.json()

    assert data["type"] == "project_created"
    assert data["status"] == "awaiting_user"
    assert data["stage"] == WorkflowState.INDUSTRY_SELECTION.value
    assert data["workflow"] == "discovery"
    assert data["domain"] == "fyp"


async def test_create_project_includes_industry_list(client: AsyncClient):
    response = await client.post("/projects")
    data = response.json()

    assert "available_industries" in data["data"]
    assert "Defense" in data["data"]["available_industries"]
    assert "Healthcare" in data["data"]["available_industries"]


async def test_create_project_allows_select_industry(client: AsyncClient):
    response = await client.post("/projects")
    data = response.json()

    assert "selectIndustry" in data["allowed_actions"]
    assert "askGrey" in data["allowed_actions"]


async def test_create_project_assigns_workspace_id(client: AsyncClient):
    response = await client.post("/projects")
    data = response.json()

    assert "workspace_id" in data
    assert len(data["workspace_id"]) > 0


# ── POST /projects/{id}/industry ──────────────────────────────────────────────

async def test_select_industry_returns_branch_event(client: AsyncClient):
    # Create project first
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    # Select industry
    response = await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Defense"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["type"] == "industry_saved"
    assert data["stage"] == WorkflowState.BRANCH_SELECTION.value
    assert data["status"] == "awaiting_user"


async def test_select_industry_returns_branches(client: AsyncClient):
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    response = await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Defense"},
    )
    data = response.json()

    assert "available_branches" in data["data"]
    assert "Navy" in data["data"]["available_branches"]
    assert data["data"]["industry"] == "Defense"


async def test_select_industry_persists_to_brain(client: AsyncClient):
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Healthcare"},
    )

    # Read back from the Project Brain
    get_resp = await client.get(f"/projects/{workspace_id}")
    snapshot = get_resp.json()

    assert snapshot["industry"] == "Healthcare"
    assert snapshot["industry_status"] == "approved"


async def test_select_invalid_industry_returns_400(client: AsyncClient):
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    response = await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Underwater Basket Weaving"},
    )
    assert response.status_code == 400


async def test_select_industry_unknown_project_returns_404(client: AsyncClient):
    response = await client.post(
        "/projects/does-not-exist/industry",
        json={"industry": "Defense"},
    )
    assert response.status_code == 404


# ── POST /projects/{id}/branch ────────────────────────────────────────────────

async def test_select_branch_returns_evidence_research_event(client: AsyncClient):
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Defense"},
    )
    response = await client.post(
        f"/projects/{workspace_id}/branch",
        json={"branch": "Navy"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["type"] == "branch_saved"
    assert data["stage"] == WorkflowState.EVIDENCE_RESEARCH.value
    assert data["status"] == "awaiting_user"
    # Release 0.2: the student can now start evidence research.
    assert data["allowed_actions"] == ["startResearch"]


async def test_select_branch_persists_to_brain(client: AsyncClient):
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Defense"},
    )
    await client.post(
        f"/projects/{workspace_id}/branch",
        json={"branch": "Navy"},
    )

    get_resp = await client.get(f"/projects/{workspace_id}")
    snapshot = get_resp.json()

    assert snapshot["industry"] == "Defense"
    assert snapshot["branch"] == "Navy"
    assert snapshot["branch_status"] == "approved"
    assert snapshot["workflow_state"] == WorkflowState.EVIDENCE_RESEARCH.value


async def test_select_branch_without_industry_returns_400(client: AsyncClient):
    """Cannot select a branch before selecting an industry."""
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    response = await client.post(
        f"/projects/{workspace_id}/branch",
        json={"branch": "Navy"},
    )
    assert response.status_code == 400


async def test_select_branch_wrong_industry_returns_400(client: AsyncClient):
    """A branch that belongs to a different industry is rejected."""
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Defense"},
    )
    response = await client.post(
        f"/projects/{workspace_id}/branch",
        json={"branch": "Clinical AI"},  # Healthcare branch, not Defense
    )
    assert response.status_code == 400


async def test_select_branch_unknown_project_returns_404(client: AsyncClient):
    response = await client.post(
        "/projects/does-not-exist/branch",
        json={"branch": "Navy"},
    )
    assert response.status_code == 404


# ── GET /projects/{id} ────────────────────────────────────────────────────────

async def test_get_project_returns_snapshot(client: AsyncClient):
    create_resp = await client.post("/projects")
    workspace_id = create_resp.json()["workspace_id"]

    response = await client.get(f"/projects/{workspace_id}")
    assert response.status_code == 200
    snapshot = response.json()

    assert snapshot["workspace_id"] == workspace_id
    assert snapshot["workflow_state"] == WorkflowState.INDUSTRY_SELECTION.value


async def test_get_unknown_project_returns_404(client: AsyncClient):
    response = await client.get("/projects/does-not-exist")
    assert response.status_code == 404


# ── Full end-to-end Release 0.1 journey ──────────────────────────────────────

async def test_full_release_01_journey(client: AsyncClient):
    """
    The complete Release 0.1 flow through the real HTTP API:
    create project → select industry → select branch → EVIDENCE_RESEARCH.
    """
    # 1. Create project
    resp = await client.post("/projects")
    assert resp.status_code == 201
    workspace_id = resp.json()["workspace_id"]
    assert resp.json()["stage"] == "INDUSTRY_SELECTION"

    # 2. Select industry
    resp = await client.post(
        f"/projects/{workspace_id}/industry",
        json={"industry": "Finance"},
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "BRANCH_SELECTION"
    assert "available_branches" in resp.json()["data"]

    # 3. Select branch
    resp = await client.post(
        f"/projects/{workspace_id}/branch",
        json={"branch": "Fraud Detection"},
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "EVIDENCE_RESEARCH"
    assert resp.json()["allowed_actions"] == ["startResearch"]

    # 4. Read the final Project Brain state
    resp = await client.get(f"/projects/{workspace_id}")
    assert resp.status_code == 200
    brain = resp.json()
    assert brain["industry"] == "Finance"
    assert brain["branch"] == "Fraud Detection"
    assert brain["workflow_state"] == "EVIDENCE_RESEARCH"
