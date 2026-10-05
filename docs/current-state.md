# Grey — Current State

**Release:** 0.1 (complete)
**Last updated:** 2026-10-05
**Scope:** FYP Companion, Discovery workflow up to `EVIDENCE_RESEARCH`

This file records exactly what is implemented today — no more, no less.
For the planned product, see `docs/specs/`. For how the pieces fit together, see `docs/architecture.md`.

---

## 1. What a student can do today

1. Open the app and click **Start my FYP** → a new project is created.
2. Choose one of **15 industries** from clickable cards.
3. Choose one of that industry's **branches** (5–7 per industry, 80 in total) from clickable cards.
4. See a confirmation that Grey is ready to research evidence, showing the chosen industry and branch.

The journey stops there. Nothing after `EVIDENCE_RESEARCH` exists yet.

---

## 2. Implemented

### Backend (`Backend/`)

| Area | What exists | Location |
|---|---|---|
| Configuration | `APP_ENV`, `DATABASE_URL`, `CORS_ORIGINS` loaded from `.env` | `app/core/config/settings.py` |
| Project Brain storage | `workspace_brain` table: workspace_id, workflow_state, industry + status, branch + status, timestamps | `app/core/brain/models.py` |
| Project Brain access | `WorkspaceBrainRepository`: `create_workspace`, `get_snapshot`, `apply_decision`, `update_workflow_state` | `app/core/brain/repository.py` |
| Database | SQLAlchemy async engine; SQLite locally (`grey.db`); tables created at startup | `app/core/brain/database.py` |
| Event envelope | `GreyEvent` (type, workspace_id, domain, workflow, stage, status, data, brain_patch, allowed_actions) | `app/core/events/schemas.py` |
| Discovery workflow | LangGraph graph: `industry_selection` → `branch_selection` → `evidence_research` → END, with `interrupt()` at both selections | `app/domains/fyp/workflows/discovery/` |
| Taxonomy | Fixed list of 15 industries and their branches, with validation helpers | `app/domains/fyp/workflows/discovery/taxonomy.py` |
| API | `POST /projects`, `POST /projects/{id}/industry`, `POST /projects/{id}/branch`, `GET /projects/{id}`, `GET /health` | `app/api/projects.py`, `main.py` |
| CORS | Browser origins from `CORS_ORIGINS` (default `http://localhost:3000`) | `main.py` |

### Frontend (`Frontend/`)

| Area | What exists | Location |
|---|---|---|
| App shell | Next.js 15 App Router, Tailwind, sidebar placeholder, disabled chat input | `app/layout.tsx`, `app/page.tsx` |
| Grey UI Adapter | `GreyAgentProvider`, `useGreyUIState`, `useGreyAgent`, `useGreyActions` (`startProject`, `selectIndustry`, `selectBranch`) | `core/grey-agent/` |
| UI state | `GreyUIState` updated from each `GreyEvent`; keeps latest `eventData`; maps `brain_patch` (snake_case) to `brainSummary` (camelCase) | `core/grey-agent/GreyAgentProvider.tsx` |
| Industry choice | `IndustrySelector` cards | `domains/fyp/components/IndustrySelector.tsx` |
| Branch choice | `BranchSelector` cards | `domains/fyp/components/BranchSelector.tsx` |
| Done screen | Green "Grey is ready to research evidence" box | `app/page.tsx` |

### Tests

| Suite | Command | Count |
|---|---|---|
| Backend (pytest) | `Backend\venv\Scripts\python.exe -m pytest -q` | **74 passing** |
| Frontend (Vitest) | `cd Frontend; npm test` | **15 passing** |
| Frontend type-check | `npm run type-check` | 0 errors |
| Frontend build | `npm run build` | succeeds |

Backend breakdown: config 7, brain 8, events 5, skills 11, taxonomy 10, discovery workflow 12, API integration 21.
Frontend breakdown: adapter 3, IndustrySelector 6, BranchSelector 6.

---

## 3. Scaffolding only (exists, but does nothing yet)

| Item | Status |
|---|---|
| `SkillRegistry` + `Skill` base class | Built and tested, but **0 skills registered**. Industry/branch logic is deterministic and does not use skills. |
| `LLMGateway` | Interface only. `generate_structured()` raises `NotImplementedError`. No LLM calls anywhere. |
| CopilotKit | Packages installed (`@copilotkit/react-core`, `@copilotkit/react-ui` 1.77). **Not wired** — no `<CopilotKit>` provider, no runtime URL. |
| Future enums | `WorkflowState`, `EventType`, `AllowedAction` contain values for later releases (e.g. `PROBLEM_OPTIONS`, `research_started`, `selectProblem`). Only the Release 0.1 values are used. `EventType.STAGE_CHANGED` is defined but never sent. |
| `askGrey` action | Included in `allowed_actions` by the backend, but there is no handler on either side. |
| Sidebar, chat input | Visual placeholders; not interactive. |
| Empty folders | `Frontend/core/{chat,drawers,sidebar,shared-components}`, `Frontend/domains/fyp/{actions,routes}`. |

---

## 4. Not implemented (by design, for later releases)

- Evidence research, problem extraction, problem selection
- Any real LLM calls or web/academic search tools
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
   Verified behaviour for a project created *before* a restart:
   - selecting an industry still returns 200 and saves it, but the workflow silently starts over;
   - selecting a branch then fails with **500 Internal Server Error**.
   Projects started after the restart work normally.

2. **Project Brain `workflow_state` lags during branch selection.**
   `POST /projects/{id}/industry` saves the industry but does not update `workflow_state`, so the database still says `INDUSTRY_SELECTION` while the student is choosing a branch. It becomes `EVIDENCE_RESEARCH` correctly after the branch is saved.

3. **Refreshing the page loses the student's place.**
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

Environment files: `Backend/.env` (template `Backend/.env.example`), `Frontend/.env.local` (template `Frontend/.env.local.example`). No secrets are needed for Release 0.1.

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
