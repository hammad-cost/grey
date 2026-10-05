# Grey — Architecture (as built)

**Last updated:** 2026-10-05 (Release 0.1)

This describes the architecture that **actually exists in the code**.
The target architecture is defined in `docs/specs/` (backend and frontend blueprints v2). Where the two differ, see §6.

---

## 1. Big picture

```
┌──────────────────────── Frontend (Next.js, :3000) ─────────────────────────┐
│ app/page.tsx  ── picks a component by GreyUIState.currentStage              │
│   └ domains/fyp/components/  IndustrySelector, BranchSelector              │
│        └ core/grey-agent/    Grey UI Adapter (provider + hooks)            │
│              useGreyActions() ── fetch() ──────────────┐                    │
└────────────────────────────────────────────────────────┼────────────────────┘
                                                         │ HTTP + JSON (CORS)
┌──────────────────────── Backend (FastAPI, :8000) ──────▼────────────────────┐
│ app/api/projects.py   thin routes: validate → workflow → Brain → GreyEvent  │
│   ├ app/domains/fyp/workflows/discovery/   LangGraph Discovery graph        │
│   │     (MemorySaver checkpointer, thread_id = workspace_id)                │
│   ├ app/core/brain/      WorkspaceBrainRepository → SQLAlchemy → SQLite     │
│   └ app/core/events/     GreyEvent envelope                                 │
│ app/core/skills/, app/core/llm/   scaffolding only (unused in 0.1)          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend layout

```
Backend/
├── main.py                         FastAPI app, CORS, router, create tables on startup
└── app/
    ├── api/projects.py             HTTP routes (thin)
    ├── core/                       shared, domain-independent
    │   ├── config/                 Settings from .env
    │   ├── brain/                  Project Brain: model, schemas, repository, database
    │   ├── events/                 GreyEvent envelope + enums
    │   ├── skills/                 Skill base class + SkillRegistry (empty)
    │   └── llm/                    LLMGateway interface (not connected)
    └── domains/fyp/                FYP-specific code
        ├── schemas/requests.py     request bodies
        └── workflows/discovery/    state, nodes, graph, taxonomy
```

**Responsibilities**

| Part | Owns | Does not |
|---|---|---|
| Route (`api/`) | Input validation, HTTP errors (400/404), calling workflow + repository, building the `GreyEvent` | Business rules beyond validation |
| Workflow (`domains/fyp/workflows/discovery/`) | Stage order, pausing for student input (`interrupt`), validating choices | Touching the database, deciding UI |
| Repository (`core/brain/repository.py`) | All reads/writes of Project Brain | Workflow logic |
| Taxonomy (`taxonomy.py`) | The fixed industry/branch lists | — (deterministic data, no AI) |

**One request, step by step** (e.g. select industry):
1. Route checks the industry is in the taxonomy (400 if not) and the project exists (404 if not).
2. Route resumes the graph: `graph.ainvoke(Command(resume=industry), thread_id=workspace_id)`.
3. Node validates again, updates execution state, graph pauses at the next `interrupt`.
4. Route calls `repo.apply_decision(workspace_id, "industry", value)` → saved as `approved`.
5. Route returns a `GreyEvent` describing the new stage and allowed actions.

---

## 3. Two kinds of state

| | Project Brain | LangGraph state |
|---|---|---|
| Purpose | Accepted decisions — **source of truth** | Where the workflow is paused |
| Stored in | Database (`workspace_brain` table) | `MemorySaver` (process memory) |
| Survives restart | Yes | **No** |
| Written by | API route via repository | LangGraph |

The frontend's `GreyUIState` is a third, display-only copy. It is rebuilt from events and is never treated as truth.

---

## 4. Frontend layout

```
Frontend/
├── app/                    layout.tsx (shell + provider), page.tsx (stage → component)
├── core/grey-agent/        Grey UI Adapter — the only place that talks to the backend
│   ├── types.ts            GreyUIState, GreyEvent, Actions
│   ├── GreyAgentProvider   holds state; applyEvent(); maps brain_patch → brainSummary
│   ├── hooks.ts            useGreyUIState, useGreyAgent, useGreyActions (fetch calls)
│   └── index.ts            public exports — components import only from here
└── domains/fyp/components/ IndustrySelector, BranchSelector
```

**Rules in force**
- Product components import from `@/core/grey-agent` only — never from CopilotKit or `fetch` directly.
- What to render is decided by `currentStage` **and** `allowedActions` from the latest backend event.
- Option lists (industries, branches) come from `eventData`, never hardcoded in the UI.

---

## 5. Contract between frontend and backend

Every state-changing response is a `GreyEvent`:

```json
{
  "type": "industry_saved",
  "workspace_id": "…",
  "domain": "fyp",
  "workflow": "discovery",
  "stage": "BRANCH_SELECTION",
  "status": "awaiting_user",
  "data": { "industry": "Finance", "available_branches": ["Banking", "…"] },
  "brain_patch": { "industry": "Finance", "industry_status": "approved" },
  "allowed_actions": ["selectBranch", "askGrey"]
}
```

- Backend uses **snake_case**; the adapter converts `brain_patch` keys to camelCase (`industryStatus`, `branchStatus`, `workflowState`).
- Transport: plain HTTP `POST`/`GET`, one request → one event. No streaming.
- CORS origins come from `CORS_ORIGINS` in `Backend/.env`.

---

## 6. Differences from the blueprints (`docs/specs/`)

| Blueprint says | Built in 0.1 | Why / next step |
|---|---|---|
| CopilotKit handles agent interaction, shared state, actions, streaming | CopilotKit **installed but not wired**. The Grey adapter calls FastAPI with `fetch`. | No AI or chat in 0.1. The adapter's hooks are the seam where CopilotKit plugs in later without changing components. |
| Workflows run through an orchestrator using skills | Routes call the graph directly; **no skills registered** | Industry/branch are deterministic. First skill expected with evidence research. |
| Durable workflow execution | `MemorySaver` (in-memory) checkpointer | Simple for 0.1. A persistent checkpointer is needed before real use (see `current-state.md` §5). |
| PostgreSQL / Supabase | SQLite via `DATABASE_URL` | Swappable by config; no migrations tool yet (`create_all` at startup). |
| — | Backend CORS middleware | Added because the browser calls the API directly from another port. |

---

## 7. Testing setup

| | Tool | Location | Notes |
|---|---|---|---|
| Backend | pytest + pytest-asyncio + httpx | `Backend/tests/unit`, `Backend/tests/integration` | Integration tests use in-memory SQLite and a fresh `MemorySaver` via FastAPI dependency overrides. |
| Frontend | Vitest 5 + jsdom + Testing Library | `*.test.tsx` next to the code | Config: `Frontend/vitest.config.mts`. Component tests mock `@/core/grey-agent`; adapter tests fake only `fetch`. No browser end-to-end tool (by decision). |
