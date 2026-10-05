# Grey — Architecture (as built)

**Last updated:** 2026-10-05 (Release 0.2)

This describes the architecture that **actually exists in the code**.
The target architecture is defined in `docs/specs/` (backend and frontend blueprints v2). Where the two differ, see §6.

---

## 1. Big picture

```
┌──────────────────────── Frontend (Next.js, :3000) ─────────────────────────┐
│ app/page.tsx  ── picks a component by GreyUIState.currentStage              │
│   └ domains/fyp/components/  IndustrySelector, BranchSelector,             │
│                              ResearchProgressCard                          │
│        └ core/grey-agent/    Grey UI Adapter (provider + hooks + stream)   │
│              useGreyActions() ── fetch() ──────────────┐                    │
└────────────────────────────────────────────────────────┼────────────────────┘
                              HTTP + JSON, NDJSON stream │ (CORS)
┌──────────────────────── Backend (FastAPI, :8000) ──────▼────────────────────┐
│ app/api/projects.py, research.py   thin routes                              │
│   ├ app/domains/fyp/workflows/discovery/   LangGraph Discovery graph        │
│   │     (MemorySaver checkpointer, thread_id = workspace_id)                │
│   │     └ research_runner.py  runs evidence_research, yields GreyEvents     │
│   ├ app/core/skills/     SkillRegistry ← ResearchEvidenceSkill (FYP)        │
│   │     └ app/core/tools/  SearchProvider ← MockSearchProvider             │
│   ├ app/core/brain/      WorkspaceBrainRepository → SQLAlchemy → SQLite     │
│   └ app/core/events/     GreyEvent envelope                                 │
│ app/core/llm/   scaffolding only (no LLM calls yet)                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend layout

```
Backend/
├── main.py                         FastAPI app, CORS, routers; on startup: create tables, register skills
└── app/
    ├── api/projects.py             discovery routes (thin)
    ├── api/research.py             research stream + evidence routes (thin)
    ├── core/                       shared, domain-independent
    │   ├── config/                 Settings from .env
    │   ├── brain/                  Project Brain: model, schemas, repository, database
    │   ├── events/                 GreyEvent envelope + enums
    │   ├── skills/                 Skill base class + SkillRegistry
    │   ├── tools/                  SearchProvider interface, MockSearchProvider, factory
    │   └── llm/                    LLMGateway interface (not connected)
    └── domains/fyp/                FYP-specific code
        ├── schemas/                request + response bodies
        ├── skills/research_evidence/  ResearchEvidenceSkill: queries, classification rules
        └── workflows/discovery/    state, nodes, graph, taxonomy, research_runner, research_events
```

**Responsibilities**

| Part | Owns | Does not |
|---|---|---|
| Route (`api/`) | Input validation, HTTP errors (400/404), calling workflow + repository, building the `GreyEvent` | Business rules beyond validation |
| Workflow (`domains/fyp/workflows/discovery/`) | Stage order, pausing for student input (`interrupt`), validating choices | Touching the database, deciding UI |
| Repository (`core/brain/repository.py`) | All reads/writes of Project Brain | Workflow logic |
| Taxonomy (`taxonomy.py`) | The fixed industry/branch lists | — (deterministic data, no AI) |
| Research runner (`research_runner.py`) | Checking research may start, recording the run, streaming the graph's progress as events | Research logic |
| Skill (`domains/fyp/skills/`) | Searching, classifying and ranking evidence | Touching the database or HTTP |
| Tool (`core/tools/`) | Talking to a search provider | Knowing about students or workflows |

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
| Stored in | Database (`workspace_brain`, `research_run`, `evidence_source`) | `MemorySaver` (process memory) |
| Survives restart | Yes | **No** (research rebuilds its position from the Brain) |
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
│   ├── stream.ts           readEventStream(): reads one GreyEvent per line from a streamed response
│   └── index.ts            public exports — components import only from here
└── domains/fyp/components/ IndustrySelector, BranchSelector, ResearchProgressCard
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
- Transport: plain HTTP `POST`/`GET`, one request → one event — except `POST /projects/{id}/research`, which streams many events as newline-delimited JSON (`application/x-ndjson`). Errors before the stream starts are HTTP errors (404/409); failures during it arrive as a `research_failed` event.
- CORS origins come from `CORS_ORIGINS` in `Backend/.env`.

---

## 6. Differences from the blueprints (`docs/specs/`)

| Blueprint says | Built in 0.1 | Why / next step |
|---|---|---|
| CopilotKit handles agent interaction, shared state, actions, streaming | CopilotKit **installed but not wired**. The Grey adapter calls FastAPI with `fetch`. | No AI or chat in 0.1. The adapter's hooks are the seam where CopilotKit plugs in later without changing components. |
| Workflows run through an orchestrator using skills | Routes call the graph (or the research runner) directly. The `evidence_research` node uses the first skill, `research_evidence`, via the `SkillRegistry`. | Industry/branch are deterministic. No separate orchestrator yet. |
| Streaming via CopilotKit | Research progress streams over a plain `fetch` + NDJSON reader in the adapter | Same events, no CopilotKit runtime needed yet. |
| Real web / academic search | `MockSearchProvider` only | By decision: real vendor only after the 0.2 architecture is verified. Adding one = a new adapter in `core/tools/providers/` + one line in the factory. |
| Durable workflow execution | `MemorySaver` (in-memory) checkpointer | Simple for 0.1. A persistent checkpointer is needed before real use (see `current-state.md` §5). |
| PostgreSQL / Supabase | SQLite via `DATABASE_URL` | Swappable by config; no migrations tool yet (`create_all` at startup). |
| — | Backend CORS middleware | Added because the browser calls the API directly from another port. |

---

## 7. Testing setup

| | Tool | Location | Notes |
|---|---|---|---|
| Backend | pytest + pytest-asyncio + httpx | `Backend/tests/unit`, `Backend/tests/integration` | Integration tests (`tests/integration/conftest.py`) use in-memory SQLite, a fresh `MemorySaver`, and their own skill registry with a no-delay mock search, via FastAPI dependency overrides. |
| Frontend | Vitest 5 + jsdom + Testing Library | `*.test.tsx` next to the code | Config: `Frontend/vitest.config.mts`. Component tests mock `@/core/grey-agent`; adapter tests fake only `fetch`. No browser end-to-end tool (by decision). |
