# Grey — Current State

**Release:** 0.1 (`9a025a1`) · 0.2 (`8cb7d3c`) · 0.3 Problem Opportunities (complete) · **0.4 Real evidence (built and tested; live run with real keys still pending)**
**Last updated:** 2026-10-06
**Scope:** FYP Companion, Discovery workflow from "Start my FYP" to a chosen, evidence-backed problem

This file records exactly what is implemented today — no more, no less.
For the planned product, see `docs/specs/`. For how the pieces fit together, see `docs/architecture.md`.
For the quick recovery checkpoint (current step, next action), see `docs/resume.md`.

---

## 0a. Release 0.4 (Real evidence) — what it added

| Step | Built | Location |
|---|---|---|
| 1 | Search gateway: several search providers behind one `SearchProvider`, tried in order (`SEARCH_PROVIDERS`); retries with backoff / retry-after; fallback on rate limit, out of credits, bad key, server error or no results; per-provider rest periods; never falls back to mock. `SearchQuery` gains `include_domains`, `recency_days`; `SearchResult.provider`; one error class per failure. | `Backend/app/core/tools/search.py`, `search_gateway.py`, `factory.py` |
| 2 | Adapters (httpx, no SDKs): **SerpAPI** (Google web, Google News tab, Google Scholar; `site:` filters; date filters) and **Tavily** (general/news, `include_domains`, `time_range`). Vendor errors translated (SerpAPI 429 "out of searches" = quota; Tavily 432/433 = quota). | `Backend/app/core/tools/providers/serpapi.py`, `tavily.py`, `common.py` |
| 3 | Editable site lists (startup directories, trusted news, peer-reviewed publishers, preprints, government endings worldwide, international bodies, data portals, community datasets, social/blogs); list checks before word clues; organization names from Scholar venue / publisher / host; snippet cleaning. | `Backend/app/domains/fyp/skills/research_evidence/sources.py`, `classification.py` |
| 4 | Research plan v2 — six steps: discover startups (directories, Tier C) → **confirm on startup websites** (second hop, Tier A) → industry news → government (2 searches) → research papers (Scholar) → datasets. Search budget `RESEARCH_MAX_SEARCHES=15`; at most 5 startups confirmed. New evidence category `news`. | `queries.py`, `startups.py`, `skill.py` |
| 5 | Research summary adds `startups_confirmed`; clear startup warning when a listed search provider has no key. | `skill.py`, `research_events.py`, `factory.py` |
| 6 | UI: research card describes the six steps and shows found-by-type; View sources labels each source (Startup website / Startup directory / News / Research paper / Government / Dataset …); "Sample data" badge whenever search or LLM is fake. | `Frontend/domains/fyp/` |
| 7 | **Pending:** live tests and one full live run (needs `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `GROQ_API_KEY`). | — |
| 8 | Docs + full verification | `docs/` |

**Mock search is still the default** (`SEARCH_PROVIDERS=mock`). Real search starts when `Backend/.env` has `SEARCH_PROVIDERS=serpapi,tavily` and the keys. Automated tests always use mock search and the fake LLM.

---

## 0. Release 0.3 (Problem Opportunities) — what it added

| Step | Built | Location |
|---|---|---|
| 1 | Project Brain: `problem_run`, `problem_candidate`, `problem_evidence` tables; repository `start/complete/fail_problem_run`, `list_problem_candidates`, `get_latest_problem_run`, `select_problem`; snapshot gains `problem_run` and `selected_problem`. Options can only cite this project's stored evidence; data and stage move together in one commit; evidence can't be replaced once options exist. | `Backend/app/core/brain/` |
| 2 | LLM layer: Grey-owned `LLMGateway`; skills request a **profile** (`fast_cheap`, `structured_reasoning`, `high_quality_reasoning`, `writing`, `long_context`); ordered fallback routes; retries with backoff / `retry-after`; per-attempt timeout + total deadline; in-memory provider health and cooldowns; Pydantic validation + one repair; usage logging (no prompts, input or keys). Providers: `FakeLLMProvider` (default) and `OpenAICompatibleProvider` configured for **Groq** (httpx, no vendor SDK). Safety refusals never fall back. | `Backend/app/core/llm/` |
| 3 | `ProblemExtractionSkill` (profile `structured_reasoning`): reads evidence through a read-only `EvidenceReader`; builds a small context (≤20 sources, refs `E1…`, no URLs/ids/queries); one gateway call; deterministic checks (refs exist, supporting points grounded in the source text, ≥1 Tier A/B, no organization names in title/direction, no URLs, length); merges duplicates, ranks, keeps 3–5; one retry with feedback, never pads. Prompt is versioned in its own file. Fake-mode responder for running without a key. | `Backend/app/domains/fyp/skills/problem_extraction/`, `app/domains/fyp/prompts/problem_extraction.py`, `app/core/brain/readers.py` |
| 4 | Workflow: graph pauses before `problem_extraction`, runs it, then waits in `problem_selection` (mandatory `interrupt`). `problem_runner.py` streams `problem_extraction_started → _progress ×4 → problem_options_ready` (or `problem_extraction_failed`), saves options with the workflow's ids, rebuilds position from the Brain after a restart; `choose_problem()` resumes the HITL pause (rebuilt from the Brain if needed). | `Backend/app/domains/fyp/workflows/discovery/` |
| 5 | API: `POST /projects/{id}/problems` (NDJSON stream), `POST /projects/{id}/problem`, `GET /projects/{id}/problems`. The skill reads evidence through `SessionEvidenceReader` (own short session, finishes even if the tab closes — fixes a SQLite lock). | `Backend/app/api/problems.py` |
| 6 | Frontend adapter: `startResearch()` continues straight into finding problems when research allows `extractProblems`; `extractProblems()` (retry); `selectProblem(id)`; `brainSummary` gains `problemStatus`, `problemOptionCount`, `selectedProblemId`, `selectedProblemTitle`; state keeps `lastEventType`. | `Frontend/core/grey-agent/` |
| 7 | UI: `ProblemProgressCard`, `ProblemOptions` + `ProblemOpportunityCard` (View sources, "Sample data" badge, confirm step), `SelectedProblemCard`; `ResearchProgressCard` shrinks to one line once problems are being found; shared `StepChecklist`. | `Frontend/domains/fyp/` , `app/page.tsx` |
| 8 | Docs + full verification | `docs/` |

**Behaviour changes vs 0.2:**
- After research the graph pauses before `problem_extraction` instead of ending.
- `research_completed` now allows `extractProblems` (was none).
- Research can't be run again once problem options exist (409).
- `LLMGateway` is real now (the 0.1 stub that raised `NotImplementedError` is gone).

The LLM runs in **fake mode by default** (no key, no cost); with `LLM_MODE=live` and `GROQ_API_KEY` set, Groq is used. (Search became real-capable in 0.4, above.)

---

## 1. What a student can do today

1. Open the app and click **Start my FYP** → a new project is created.
2. Choose one of **15 industries**, then one of that industry's **branches** (80 in total).
3. Click **Start research** and watch a six-step checklist (discover startups → confirm on startup websites → industry news → government → research papers → datasets) with running source counts, then a summary by type (e.g. "3 startups confirmed · 2 news articles · …").
4. Without clicking again, watch Grey find problems in the evidence (second live checklist).
5. See **3–5 problem cards**, each with the real-world problem, why it matters, a possible FYP direction, evidence strength (Tier A/B/C) and **View sources** (source type, title + link, organization, date, tier, the point each source supports).
6. Choose one → confirm → see **Your FYP problem** with industry, branch, direction and source count.

On any failure: a calm message and **Try again** (or **Research again** when the evidence was too thin).
The journey stops at the chosen problem. Functional-area classification, FYP direction and everything after it do not exist yet.

---

## 2. Implemented

### Backend (`Backend/`)

| Area | What exists | Location |
|---|---|---|
| Configuration | `APP_ENV`, `DATABASE_URL`, `CORS_ORIGINS`, `SEARCH_PROVIDERS`, `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `RESEARCH_MAX_SEARCHES`, `SEARCH_TIMEOUT_SECONDS`, `SEARCH_MAX_RETRIES`, `SEARCH_COOLDOWN_SECONDS`, `SEARCH_QUOTA_COOLDOWN_SECONDS`, `MOCK_SEARCH_DELAY_MS`, `LLM_MODE`, `GROQ_API_KEY`, `GROQ_BASE_URL`, `LLM_PROFILE_*` overrides, `LLM_TIMEOUT_SECONDS`, `LLM_TOTAL_DEADLINE_SECONDS`, `LLM_MAX_RETRIES`, `LLM_COOLDOWN_SECONDS`, `LLM_QUOTA_COOLDOWN_SECONDS` | `app/core/config/settings.py`, `.env.example` |
| Project Brain storage | `workspace_brain`; `research_run`, `evidence_source` (0.2); `problem_run`, `problem_candidate`, `problem_evidence` (0.3) | `app/core/brain/models.py` |
| Project Brain access | `WorkspaceBrainRepository` (decisions, research, evidence, problems, selection); read-only `EvidenceReader` / `SessionEvidenceReader` for skills | `app/core/brain/repository.py`, `readers.py` |
| Database | SQLAlchemy async engine; SQLite locally (`grey.db`); tables created at startup (new tables are added to an existing `grey.db` automatically) | `app/core/brain/database.py` |
| Event envelope | `GreyEvent` (type, workspace_id, domain, workflow, stage, status, data, brain_patch, allowed_actions) | `app/core/events/schemas.py` |
| Discovery workflow | `industry_selection` → `branch_selection` → ⏸ → `evidence_research` → ⏸ → `problem_extraction` → `problem_selection` (interrupt) → END | `app/domains/fyp/workflows/discovery/` |
| Skills | `research_evidence` (search tool, no LLM; six steps incl. second-hop startup confirmation) and `problem_extraction` (LLM via gateway), registered at startup | `app/domains/fyp/skills/`, `main.py` |
| Search tool | `SearchGateway` (ordered fallback) over `SerpApiProvider`, `TavilySearchProvider`; `MockSearchProvider` by default | `app/core/tools/` |
| LLM layer | Gateway, profiles, router, health, errors, schema tools; Fake + OpenAI-compatible (Groq) providers | `app/core/llm/` |
| Taxonomy | 15 industries, 80 branches, validation helpers | `app/domains/fyp/workflows/discovery/taxonomy.py` |
| API | `POST /projects`, `POST /projects/{id}/industry`, `POST /projects/{id}/branch`, `GET /projects/{id}`, `POST /projects/{id}/research` (stream), `GET /projects/{id}/evidence`, `POST /projects/{id}/problems` (stream), `POST /projects/{id}/problem`, `GET /projects/{id}/problems`, `GET /health` | `app/api/`, `main.py` |
| CORS | Browser origins from `CORS_ORIGINS` (default `http://localhost:3000`) | `main.py` |

### Frontend (`Frontend/`)

| Area | What exists | Location |
|---|---|---|
| App shell | Next.js 15 App Router, Tailwind, sidebar placeholder, disabled chat input | `app/layout.tsx`, `app/page.tsx` |
| Grey UI Adapter | `GreyAgentProvider`, `useGreyUIState`, `useGreyAgent`, `useGreyActions` (`startProject`, `selectIndustry`, `selectBranch`, `startResearch`, `extractProblems`, `selectProblem`), `readEventStream` | `core/grey-agent/` |
| UI state | `GreyUIState` from each `GreyEvent`: latest `eventData` + `lastEventType`, `progress`, `brainSummary` (camelCase from `brain_patch`) | `core/grey-agent/GreyAgentProvider.tsx` |
| Discovery cards | `IndustrySelector`, `BranchSelector`, `ResearchProgressCard`, `ProblemProgressCard`, `ProblemOptions`, `ProblemOpportunityCard`, `SelectedProblemCard`, `StepChecklist` | `domains/fyp/components/` |
| Problem parsing | `readProblems`, `readProblem`, `isSampleData`, task-type labels | `domains/fyp/problems.ts` |

### Tests

| Suite | Command | Count |
|---|---|---|
| Backend (pytest) | `Backend\venv\Scripts\python.exe -m pytest -q` | **567 passing, 1 skipped** (the live Groq test) |
| Backend live LLM | `$env:RUN_LIVE_LLM_TESTS="1"; ...pytest -m live_llm -s` | 1 test, needs `GROQ_API_KEY`; uses a little Groq quota |
| Frontend (Vitest) | `cd Frontend; npm test` | **67 passing** |
| Frontend type-check | `npm run type-check` | 0 errors |
| Frontend build | `npm run build` | succeeds |

Every automated test uses `FakeLLMProvider` and `MockSearchProvider` — `tests/conftest.py` forces `LLM_MODE=fake` and `SEARCH_PROVIDERS=mock` even if `.env` says otherwise. No keys used, no credits spent.

---

## 3. Scaffolding only (exists, but does nothing yet)

| Item | Status |
|---|---|
| LLM profiles other than `structured_reasoning` | Defined and configurable; no skill uses them yet. |
| CopilotKit | Packages installed. **Not wired** — the adapter uses `fetch` + an NDJSON reader. |
| Future enums | `WorkflowState`, `EventType`, `AllowedAction` contain values for later releases (e.g. `AREA_CLASSIFICATION`, `fyp_direction_ready`, `requestMoreProblems`). `EventType.STAGE_CHANGED` is defined but never sent. |
| `askGrey` action | Included in some `allowed_actions`, but no handler on either side. |
| Sidebar, chat input | Visual placeholders; not interactive. |
| Empty folders | `Frontend/core/{chat,drawers,sidebar,shared-components}`, `Frontend/domains/fyp/{actions,routes}`. |

---

## 4. Not implemented (by design, for later releases)

- Functional-area classification, FYP direction, scope, datasets and everything after problem selection
- Asking for more / different problems, or going back to change an earlier decision
- Paid startup databases (Dealroom / Crunchbase APIs) — public pages are found through search only
- Reading full web pages (only search snippets are used)
- Proactive credit tracking per search provider (Grey reacts to "limit reached" errors instead)
- LLM providers other than Groq (Anthropic, OpenAI, LiteLLM — the design allows adding them as adapters)
- Persistent LLM usage/cost records (logged only), shared provider health across server processes
- A list of all saved evidence in the app (problem cards show their own sources)
- CopilotKit chat or agent runtime
- User accounts, authentication, listing or reopening projects
- PostgreSQL / Supabase (SQLite only; switching is a `DATABASE_URL` change); database migrations

---

## 5. Known issues and limitations

1. **Workflow progress is lost when the backend restarts** (`MemorySaver`).
   - Industry/branch steps (0.1): a project started *before* a restart can hit **500** at the branch step.
   - Research, problem extraction and problem selection are **not affected**: they rebuild the workflow position from the Brain and replace runs left "running" by a stopped server.

2. **Project Brain `workflow_state` lags during branch selection** (stays `INDUSTRY_SELECTION` until the branch is saved).

3. **Refreshing the page loses the student's place on screen.** The frontend never reloads from `GET /projects/{id}` / `GET /projects/{id}/problems`. All data stays in the database.

4. **Industry and branch are validated twice** (route and node) — harmless; both read `taxonomy.py`.

5. **Industry/branch saving is not atomic** (workflow first, Brain second). Problem options and selection *are* saved atomically with their stage.

6. **Fake-mode problems are pattern-based.** With `LLM_MODE=fake` the problems are built from simple keyword rules over the sample evidence — fine for exercising the app, not real reasoning. The "Sample data" badge says so.

7. **Groq free tier is small** (about 8,000 tokens/minute and 200,000/day per model). The context is kept small to fit; heavy testing can hit the daily limit (Grey then falls back to the second model, then shows "try again").

8. **Real search is untested against the live services yet** (Step 7 of 0.4). The adapters are built from the vendors' docs and tested against recorded-shape responses; the first live run may need small fixes.

9. **Second-hop startup matching is strict.** A startup counts as confirmed only if its name appears in the website address, so some real startups may be missed (fewer Tier A sources), but a wrong site is not marked official.

10. **Free search plans are small.** One research run uses about 12 searches (cap 15). When SerpAPI runs out, Grey switches to Tavily; when both run out, research shows "please try again".

---

## 6. Environment

| Tool | Version |
|---|---|
| Python | 3.13 (venv at `Backend/venv`) |
| Node.js / npm | 22.14 / 11.12 |
| FastAPI / LangGraph / SQLAlchemy / httpx | 0.115.6 / 1.2.12 / 2.0.36 / 0.28.1 |
| Next.js / React / TypeScript | 15.5 / 19.3 / 5.9 |
| Vitest / jsdom / Testing Library | 5.0 / 29 / 16 |

Environment files: `Backend/.env` (template `Backend/.env.example`), `Frontend/.env.local` (template `Frontend/.env.local.example`).
To use real services, in `Backend/.env` (never commit it):
```ini
LLM_MODE=live
GROQ_API_KEY=...
SEARCH_PROVIDERS=serpapi,tavily
SERPAPI_API_KEY=...
TAVILY_API_KEY=...
```

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
