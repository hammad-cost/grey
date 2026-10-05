# Grey — Current State

**Release:** 0.1 complete (commit `9a025a1`) · **0.2 complete** (Evidence Research, all 8 steps)
**Last updated:** 2026-10-05
**Scope:** FYP Companion, Discovery workflow up to and including evidence research

This file records exactly what is implemented today — no more, no less.
For the planned product, see `docs/specs/`. For how the pieces fit together, see `docs/architecture.md`.
For the quick recovery checkpoint (current step, next action), see `docs/resume.md`.

---

## 0. Release 0.2 (Evidence Research) — what it added

| Step | Built | Location |
|---|---|---|
| 1 | Project Brain storage: `research_run` and `evidence_source` tables; repository methods `start_research_run`, `complete_research_run`, `fail_research_run`, `list_evidence`, `get_latest_research_run`; snapshot includes latest `research` run | `Backend/app/core/brain/` |
| 2 | Provider-independent search tool (`SearchProvider`, `SearchQuery`, `SearchResult`, `SearchFocus`), `MockSearchProvider` (reserved `.example` URLs), `get_search_provider`; settings `SEARCH_PROVIDER=mock`, `MOCK_SEARCH_DELAY_MS=400` | `Backend/app/core/tools/`, `app/core/config/settings.py` |
| 3 | `ResearchEvidenceSkill`: 5 searches over 4 categories, rule-based source type + Tier A/B/C, all blueprint evidence fields, de-dup, max 5 per category, strongest first; `register_fyp_skills()` | `Backend/app/domains/fyp/skills/` |
| 4 | Workflow: graph pauses before `evidence_research`; node calls the skill via the Skill Registry; `start_evidence_research()` runner streams `research_started → searching_sources/sources_found ×4 → evaluating_evidence → storing_evidence → research_completed` (or `research_failed`); rebuilds workflow position from the Brain after a restart; replaces runs orphaned by a stopped server | `Backend/app/domains/fyp/workflows/discovery/` |
| 5 | API: `POST /projects/{id}/research` (NDJSON stream, own DB session; 404/409 before streaming), `GET /projects/{id}/evidence`; skills registered at startup (`register_skills()`); `branch_saved` now `awaiting_user` with `allowed_actions: ["startResearch"]` | `Backend/app/api/research.py`, `main.py`, `app/api/projects.py` |
| 6 | Frontend adapter: `startResearch()` + `readEventStream()`; research events set `GreyUIState.progress`; `brainSummary` gains `researchStatus`, `evidenceCount`, `highQualityEvidenceCount`; error if the stream stops before research ends | `Frontend/core/grey-agent/` |
| 7 | `ResearchProgressCard` (ready / running checklist / complete summary / failed + Try again) replaces the old "Release 0.1 complete" box | `Frontend/domains/fyp/components/ResearchProgressCard.tsx`, `app/page.tsx` |
| 8 | Docs + full verification | `docs/` |

**Behaviour changes vs 0.1:**
- After branch selection the Discovery graph **pauses before** `evidence_research` instead of ending.
- `branch_saved` has status `awaiting_user` (was `complete`) and allows `startResearch` (was none).
- `EventType` values `research_progress` / `research_complete` were replaced by the 0.2 names above.

**Search is mock only.** Every source is sample data with a reserved `.example` URL. No real web search and no LLM calls.

---

## 1. What a student can do today

1. Open the app and click **Start my FYP** → a new project is created.
2. Choose one of **15 industries** from clickable cards.
3. Choose one of that industry's **branches** (5–7 per industry, 80 in total) from clickable cards.
4. See that Grey is ready to research evidence and click **Start research**.
5. Watch a live checklist (organizations → official sources → research → datasets → evaluating → saving) with running source counts.
6. See a summary: how many sources were saved and how many are Tier A / B / C. On failure: a calm message and **Try again**.

The journey stops there. Problem extraction and everything after it do not exist yet.
The evidence itself can be read with `GET /projects/{id}/evidence`, but the app does not list the sources yet.

---

## 2. Implemented

### Backend (`Backend/`)

| Area | What exists | Location |
|---|---|---|
| Configuration | `APP_ENV`, `DATABASE_URL`, `CORS_ORIGINS` loaded from `.env` | `app/core/config/settings.py` |
| Project Brain storage | `workspace_brain` table: workspace_id, workflow_state, industry + status, branch + status, timestamps. `research_run` and `evidence_source` tables (0.2) | `app/core/brain/models.py` |
| Project Brain access | `WorkspaceBrainRepository`: `create_workspace`, `get_snapshot`, `apply_decision`, `update_workflow_state` | `app/core/brain/repository.py` |
| Database | SQLAlchemy async engine; SQLite locally (`grey.db`); tables created at startup | `app/core/brain/database.py` |
| Event envelope | `GreyEvent` (type, workspace_id, domain, workflow, stage, status, data, brain_patch, allowed_actions) | `app/core/events/schemas.py` |
| Discovery workflow | LangGraph graph: `industry_selection` → `branch_selection` → ⏸ → `evidence_research` → END, with `interrupt()` at both selections and a pause before research | `app/domains/fyp/workflows/discovery/` |
| Evidence research | Research runner + events, `ResearchEvidenceSkill`, `MockSearchProvider` | see §0 |
| Taxonomy | Fixed list of 15 industries and their branches, with validation helpers | `app/domains/fyp/workflows/discovery/taxonomy.py` |
| API | `POST /projects`, `POST /projects/{id}/industry`, `POST /projects/{id}/branch`, `GET /projects/{id}`, `POST /projects/{id}/research` (stream), `GET /projects/{id}/evidence`, `GET /health` | `app/api/projects.py`, `app/api/research.py`, `main.py` |
| CORS | Browser origins from `CORS_ORIGINS` (default `http://localhost:3000`) | `main.py` |

### Frontend (`Frontend/`)

| Area | What exists | Location |
|---|---|---|
| App shell | Next.js 15 App Router, Tailwind, sidebar placeholder, disabled chat input | `app/layout.tsx`, `app/page.tsx` |
| Grey UI Adapter | `GreyAgentProvider`, `useGreyUIState`, `useGreyAgent`, `useGreyActions` (`startProject`, `selectIndustry`, `selectBranch`, `startResearch`), `readEventStream` | `core/grey-agent/` |
| UI state | `GreyUIState` updated from each `GreyEvent`; keeps latest `eventData`; maps `brain_patch` (snake_case) to `brainSummary` (camelCase) | `core/grey-agent/GreyAgentProvider.tsx` |
| Industry choice | `IndustrySelector` cards | `domains/fyp/components/IndustrySelector.tsx` |
| Branch choice | `BranchSelector` cards | `domains/fyp/components/BranchSelector.tsx` |
| Research | `ResearchProgressCard` | `domains/fyp/components/ResearchProgressCard.tsx` |

### Tests

| Suite | Command | Count |
|---|---|---|
| Backend (pytest) | `Backend\venv\Scripts\python.exe -m pytest -q` | **251 passing** |
| Frontend (Vitest) | `cd Frontend; npm test` | **29 passing** |
| Frontend type-check | `npm run type-check` | 0 errors |
| Frontend build | `npm run build` | succeeds |

Backend: 74 from 0.1 + 177 from 0.2 (brain evidence, search tool, classification, research skill, research workflow, research API 14).
Frontend breakdown: adapter 6, stream reader 4, IndustrySelector 6, BranchSelector 6, ResearchProgressCard 7.

---

## 3. Scaffolding only (exists, but does nothing yet)

| Item | Status |
|---|---|
| `SkillRegistry` + `Skill` base class | In use: **1 skill registered** at startup (`research_evidence`). Industry/branch logic is deterministic and does not use skills. |
| `LLMGateway` | Interface only. `generate_structured()` raises `NotImplementedError`. No LLM calls anywhere. |
| CopilotKit | Packages installed (`@copilotkit/react-core`, `@copilotkit/react-ui` 1.77). **Not wired** — no `<CopilotKit>` provider, no runtime URL. |
| Future enums | `WorkflowState`, `EventType`, `AllowedAction` contain values for later releases (e.g. `PROBLEM_OPTIONS`, `research_started`, `selectProblem`). Only the Release 0.1 values are used. `EventType.STAGE_CHANGED` is defined but never sent. |
| `askGrey` action | Included in `allowed_actions` by the backend, but there is no handler on either side. |
| Sidebar, chat input | Visual placeholders; not interactive. |
| Empty folders | `Frontend/core/{chat,drawers,sidebar,shared-components}`, `Frontend/domains/fyp/{actions,routes}`. |

---

## 4. Not implemented (by design, for later releases)

- Problem extraction, problem selection, dataset recommendation
- Any real LLM calls or real web/academic search (mock search only)
- A list of the saved evidence sources in the app (API exists, no UI)
- CopilotKit chat, streaming, or agent runtime
- Going back / changing an earlier decision
- User accounts or authentication
- Listing or reopening existing projects
- PostgreSQL / Supabase (SQLite only so far; switching is a `DATABASE_URL` change)
- Database migrations (tables are created with `create_all` at startup)

---

## 5. Known issues and limitations

1. **Workflow progress is lost when the backend restarts.**
   The LangGraph checkpointer is `MemorySaver` (in memory). Project Brain survives in the database, but the paused workflow does not.
   Verified behaviour (0.1) for a project created *before* a restart:
   - selecting an industry still returns 200 and saves it, but the workflow silently starts over;
   - selecting a branch then fails with **500 Internal Server Error**.
   Projects started after the restart work normally.
   **Research is not affected:** it rebuilds the workflow position from the Brain, and replaces a run left "running" by a stopped server.

2. **Project Brain `workflow_state` lags during branch selection.**
   `POST /projects/{id}/industry` saves the industry but does not update `workflow_state`, so the database still says `INDUSTRY_SELECTION` while the student is choosing a branch. It becomes `EVIDENCE_RESEARCH` correctly after the branch is saved.

3. **Refreshing the page loses the student's place** (including research results on screen; the evidence stays in the database).
   The frontend keeps state only in React memory and never calls `GET /projects/{id}`, so a refresh returns to the welcome screen. The data is still in the database.

4. **Industry and branch are validated twice** — once in the API route and again in the workflow node. Harmless, but the lists must stay in sync (they both read `taxonomy.py`, so they do today).

5. **Saving is not atomic.** Each route resumes the workflow first and then writes to Project Brain in a separate step. If the database write failed, the two would disagree.

---

## 6. Environment

| Tool | Version |
|---|---|
| Python | 3.13 (venv at `Backend/venv`) |
| Node.js / npm | 22.14 / 11.12 |
| FastAPI / LangGraph / SQLAlchemy | 0.115.6 / 1.2.12 / 2.0.36 |
| Next.js / React / TypeScript | 15.5 / 19.3 / 5.9 |
| Vitest / jsdom / Testing Library | 5.0 / 29 / 16 |

Environment files: `Backend/.env` (template `Backend/.env.example`), `Frontend/.env.local` (template `Frontend/.env.local.example`). No secrets are needed (search is mock only).

**Windows note:** install frontend packages with `npm install --legacy-peer-deps` (needed by CopilotKit). Never run two installs at once — it corrupted `node_modules` once already.

---

## 7. How to run

```powershell
# Terminal 1 — backend
cd D:\Projects\Grey\Backend
.\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd D:\Projects\Grey\Frontend
npm run dev
```

Open http://localhost:3000. API docs: http://localhost:8000/docs.
