# Grey — Current State

**Release:** 0.1 (`9a025a1`) · 0.2 (`8cb7d3c`) · 0.3 + 0.4 (`ee2b0ac`, live-tested `38c2b9d`) · 0.4.1 Step 1 (`2708b85`, rest paused) · **0.5 From problem to FYP (complete, local commits, not pushed; not yet run live)**
**Last updated:** 2026-10-06
**Scope:** FYP Companion, from "Start my FYP" to an approved, evidence-backed FYP design (stage `APPROVED_FYP`)

This file records exactly what is implemented today — no more, no less.
For the planned product, see `docs/specs/`. For how the pieces fit together, see `docs/architecture.md`.
For the quick recovery checkpoint (current step, next action), see `docs/resume.md`.

---

## 0b. Release 0.5 (From problem to FYP) — what it added

| Step | Built | Location |
|---|---|---|
| 1 | Project Brain: `functional_area` (one per project), `fyp_design_run` (each design/redesign attempt: kind, adjustment, note, status, provider/model/prompt version, error), `fyp_design` (versions: `draft` / `superseded` / `approved`, adjustment + note per version). New stage `APPROVED_FYP`. Repository `start_fyp_design_run`, `save_functional_area`, `complete_fyp_design_run`, `fail_fyp_design_run`, `approve_fyp_design`, `get_functional_area`, `get_current_fyp_design`, `list_fyp_designs`, `count_fyp_adjustments`; stage checks; max **3 redesigns** (`MAX_FYP_ADJUSTMENTS`); snapshot gains `functional_area`, `fyp_design`, `fyp_adjustments_used`, `fyp_design_run`. | `Backend/app/core/brain/` |
| 2 | Skills, via the Skill Registry and `LLMGateway` only: **`classify_area`** (profile `fast_cheap`) → functional area + specific area + one-sentence explanation; **`design_fyp`** (profile `structured_reasoning`) → title, summary, target user, input, output, main contribution, how the problem was made student-sized. Plain-code checks reject links, evidence organization names, **named datasets/models/libraries/APIs/clouds/stacks** (list in `fyp_design_shared.py`), over-long fields, an area equal to the branch, and an unchanged redesign; one retry. Four controlled adjustments (`make_simpler`, `change_target_user`, `change_system_focus`, `reduce_complexity`) + optional note ≤200 chars. Versioned prompts; fake-mode answers. | `Backend/app/domains/fyp/skills/classify_area/`, `design_fyp/`, `fyp_design_shared.py`, `app/domains/fyp/prompts/classify_area.py`, `design_fyp.py` |
| 3 | Separate **`fyp_design`** LangGraph workflow: `area_classification` → `fyp_design` → `fyp_review` (interrupt: approve, or adjust → back to `fyp_design`) → END. Runner streams `fyp_design_started → fyp_design_progress → area_classified → … → fyp_direction_ready` (or `fyp_design_failed`), saves the area as soon as it is classified, saves each version, and rebuilds the workflow position from the Brain before every step (restart-safe). "Why this FYP?" is assembled by code from the stored problem and its cited evidence (`view.py`). `problem_selected` now allows `designFYP`. | `Backend/app/domains/fyp/workflows/fyp_design/` |
| 4 | API: `POST /projects/{id}/fyp-design` (stream), `POST /projects/{id}/fyp-design/adjust` (stream), `POST /projects/{id}/fyp-design/approve`, `GET /projects/{id}/fyp-design`. API version 0.5.0. | `Backend/app/api/fyp_design.py` |
| 5 | Frontend adapter: `selectProblem()` continues straight into the design when the backend allows `designFYP`; `designFYP()` (retry), `adjustFYPDirection(adjustment, note?)`, `approveFYPDirection(designId)`; `brainSummary` gains `functionalArea`, `specificArea`, `fypDesignStatus`, `fypDesignId`, `fypTitle`, `fypAdjustmentsLeft`. | `Frontend/core/grey-agent/` |
| 6 | UI: `FunctionalAreaCard` (Industry → Branch → Functional area → Specific area → Problem), `FYPDirectionCard` (live checklist; failure + Try again; review with "Why this FYP?" sources, **Approve** with confirm, **Adjust** with the four options + note and "N of 3 redesigns left"), `ApprovedFYPCard`. Data read safely by `domains/fyp/fypDesign.ts`. | `Frontend/domains/fyp/`, `app/page.tsx` |
| 7 | Docs + full verification; fake-mode end-to-end run through a real server (design → 3 redesigns → 4th refused → approve). | `docs/` |

**Behaviour changes vs 0.4:** `problem_selected` allows `designFYP` (was none), and the frontend starts the design automatically after the student confirms a problem.

The FYP design describes **what** the student builds and for whom. It never chooses a dataset, model, API or technology stack — those are later stages.

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
| 7 | Live tests (`tests/live/test_search_live.py`) + one full live run; fixed SerpAPI `site:` and the strict-schema `title` bug | `app/core/tools/providers/`, `app/core/llm/schema_tools.py` |
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
6. Choose one → confirm → see **Your FYP problem**.
7. Without clicking again, watch Grey find **Your project area** (Industry → Branch → Functional area → Specific area → Problem) and design a **Proposed FYP**: title, what you'll build, who uses it, input, output, main contribution, and **Why this FYP?** (where the problem came from, why it matters, who works on it, how Grey made it student-sized, and the sources with links).
8. Either **Approve this FYP** (with a confirm step) or **Adjust** it up to 3 times: Make project simpler · Change target user · Change system focus · Reduce implementation complexity, plus an optional short note. Each redesign keeps the same problem.
9. After approving, see **Your approved FYP**. It is saved in the Project Brain (stage `APPROVED_FYP`).

On any failure: a calm message and **Try again** (or **Research again** when the evidence was too thin). A failed redesign keeps the current design and doesn't use up a redesign.
The journey stops at the approved FYP. Scope, AI necessity/strategy, datasets, technology, architecture, evaluation, feasibility and the proposal do not exist yet.

---

## 2. Implemented

### Backend (`Backend/`)

| Area | What exists | Location |
|---|---|---|
| Configuration | `APP_ENV`, `DATABASE_URL`, `CORS_ORIGINS`, `SEARCH_PROVIDERS`, `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `RESEARCH_MAX_SEARCHES`, `SEARCH_TIMEOUT_SECONDS`, `SEARCH_MAX_RETRIES`, `SEARCH_COOLDOWN_SECONDS`, `SEARCH_QUOTA_COOLDOWN_SECONDS`, `MOCK_SEARCH_DELAY_MS`, `LLM_MODE`, `GROQ_API_KEY`, `GROQ_BASE_URL`, `LLM_PROFILE_*` overrides, `LLM_TIMEOUT_SECONDS`, `LLM_TOTAL_DEADLINE_SECONDS`, `LLM_MAX_RETRIES`, `LLM_COOLDOWN_SECONDS`, `LLM_QUOTA_COOLDOWN_SECONDS` | `app/core/config/settings.py`, `.env.example` |
| Project Brain storage | `workspace_brain`; `research_run`, `evidence_source` (0.2); `problem_run`, `problem_candidate`, `problem_evidence` (0.3); `functional_area`, `fyp_design_run`, `fyp_design` (0.5) | `app/core/brain/models.py` |
| Project Brain access | `WorkspaceBrainRepository` (decisions, research, evidence, problems, selection, area, FYP design versions, approval); read-only `EvidenceReader` / `SessionEvidenceReader` for skills | `app/core/brain/repository.py`, `readers.py` |
| Database | SQLAlchemy async engine; SQLite locally (`grey.db`); tables created at startup (new tables are added to an existing `grey.db` automatically) | `app/core/brain/database.py` |
| Event envelope | `GreyEvent` (type, workspace_id, domain, workflow, stage, status, data, brain_patch, allowed_actions) | `app/core/events/schemas.py` |
| Discovery workflow | `industry_selection` → `branch_selection` → ⏸ → `evidence_research` → ⏸ → `problem_extraction` → `problem_selection` (interrupt) → END | `app/domains/fyp/workflows/discovery/` |
| FYP Design workflow (0.5) | `area_classification` → `fyp_design` → `fyp_review` (interrupt: approve → END, adjust → `fyp_design`) | `app/domains/fyp/workflows/fyp_design/` |
| Skills | `research_evidence` (search tool, no LLM; six steps incl. second-hop startup confirmation), `problem_extraction`, `classify_area`, `design_fyp` (LLM via gateway), registered at startup | `app/domains/fyp/skills/`, `main.py` |
| Search tool | `SearchGateway` (ordered fallback) over `SerpApiProvider`, `TavilySearchProvider`; `MockSearchProvider` by default | `app/core/tools/` |
| LLM layer | Gateway, profiles, router, health, errors, schema tools; Fake + OpenAI-compatible (Groq) providers | `app/core/llm/` |
| Taxonomy | 15 industries, 80 branches, validation helpers | `app/domains/fyp/workflows/discovery/taxonomy.py` |
| API | `POST /projects`, `POST /projects/{id}/industry`, `POST /projects/{id}/branch`, `GET /projects/{id}`, `POST /projects/{id}/research` (stream), `GET /projects/{id}/evidence`, `POST /projects/{id}/problems` (stream), `POST /projects/{id}/problem`, `GET /projects/{id}/problems`, `POST /projects/{id}/fyp-design` (stream), `POST /projects/{id}/fyp-design/adjust` (stream), `POST /projects/{id}/fyp-design/approve`, `GET /projects/{id}/fyp-design`, `GET /health` | `app/api/`, `main.py` |
| CORS | Browser origins from `CORS_ORIGINS` (default `http://localhost:3000`) | `main.py` |

### Frontend (`Frontend/`)

| Area | What exists | Location |
|---|---|---|
| App shell | Next.js 15 App Router, Tailwind, sidebar placeholder, disabled chat input | `app/layout.tsx`, `app/page.tsx` |
| Grey UI Adapter | `GreyAgentProvider`, `useGreyUIState`, `useGreyAgent`, `useGreyActions` (`startProject`, `selectIndustry`, `selectBranch`, `startResearch`, `extractProblems`, `selectProblem`, `designFYP`, `adjustFYPDirection`, `approveFYPDirection`), `readEventStream` | `core/grey-agent/` |
| UI state | `GreyUIState` from each `GreyEvent`: latest `eventData` + `lastEventType`, `progress`, `brainSummary` (camelCase from `brain_patch`) | `core/grey-agent/GreyAgentProvider.tsx` |
| Discovery cards | `IndustrySelector`, `BranchSelector`, `ResearchProgressCard`, `ProblemProgressCard`, `ProblemOptions`, `ProblemOpportunityCard`, `SelectedProblemCard`, `StepChecklist` | `domains/fyp/components/` |
| FYP cards (0.5) | `FunctionalAreaCard`, `FYPDirectionCard`, `ApprovedFYPCard` | `domains/fyp/components/` |
| Event parsing | `problems.ts` (`readProblems`, `readProblem`, `isSampleData`, task-type labels); `fypDesign.ts` (`readFYP`, `readArea`, `ADJUSTMENT_OPTIONS`, `isSampleFYP`) | `domains/fyp/` |

### Tests

| Suite | Command | Count |
|---|---|---|
| Backend (pytest) | `Backend\venv\Scripts\python.exe -m pytest -q` | **674 passing, 10 skipped** (the live Groq + 9 live search tests) |
| Backend live LLM | `$env:RUN_LIVE_LLM_TESTS="1"; ...pytest -m live_llm -s` | 1 test, needs `GROQ_API_KEY`; uses a little Groq quota |
| Backend live search | `$env:RUN_LIVE_SEARCH_TESTS="1"; ...pytest -m live_search -s` | 9 tests, need `SERPAPI_API_KEY` / `TAVILY_API_KEY`; about 1 credit each |
| Frontend (Vitest) | `cd Frontend; npm test` | **104 passing** |
| Frontend type-check | `npm run type-check` | 0 errors |
| Frontend build | `npm run build` | succeeds |

Every automated test uses `FakeLLMProvider` and `MockSearchProvider` — `tests/conftest.py` forces `LLM_MODE=fake` and `SEARCH_PROVIDERS=mock` even if `.env` says otherwise. No keys used, no credits spent.

---

## 3. Scaffolding only (exists, but does nothing yet)

| Item | Status |
|---|---|
| LLM profiles `high_quality_reasoning`, `writing`, `long_context` | Defined and configurable; no skill uses them yet (`structured_reasoning` and, since 0.5, `fast_cheap` are used). |
| CopilotKit | Packages installed. **Not wired** — the adapter uses `fetch` + an NDJSON reader. |
| Future enums | `WorkflowState`, `EventType`, `AllowedAction` contain values for later releases (e.g. `SCOPE`, `dataset_options_ready`, `requestMoreProblems`, `modifyScope`). `EventType.STAGE_CHANGED` is defined but never sent. |
| `askGrey` action | Included in some `allowed_actions`, but no handler on either side. |
| Sidebar, chat input | Visual placeholders; not interactive. |
| Empty folders | `Frontend/core/{chat,drawers,sidebar,shared-components}`, `Frontend/domains/fyp/{actions,routes}`. |

---

## 4. Not implemented (by design, for later releases)

- Problem definition, scope, AI necessity/strategy, datasets, models, technology stack, architecture, evaluation, feasibility, supervisor readiness, proposal — everything after the approved FYP
- Asking for more / different problems, or going back to change an earlier decision (e.g. a different problem after the FYP design started)
- Evidence quality improvements of 0.4.1 Steps 2–4 (paused by the student's choice)
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
   - Research, problem extraction, problem selection and the whole FYP design (design, redesign, approval) are **not affected**: they rebuild the workflow position from the Brain and replace runs left "running" by a stopped server.

2. **Project Brain `workflow_state` lags during branch selection** (stays `INDUSTRY_SELECTION` until the branch is saved).

3. **Refreshing the page loses the student's place on screen.** The frontend never reloads from `GET /projects/{id}` / `GET /projects/{id}/problems`. All data stays in the database.

4. **Industry and branch are validated twice** (route and node) — harmless; both read `taxonomy.py`.

5. **Industry/branch saving is not atomic** (workflow first, Brain second). Problem options and selection *are* saved atomically with their stage.

6. **Fake-mode problems are pattern-based.** With `LLM_MODE=fake` the problems are built from simple keyword rules over the sample evidence — fine for exercising the app, not real reasoning. The "Sample data" badge says so.

7. **Groq free tier is small** (about 8,000 tokens/minute and 200,000/day per model). The context is kept small to fit; heavy testing can hit the daily limit (Grey then falls back to the second model, then shows "try again").

8. **Real search passed its live tests on 2026-10-06** (`$env:RUN_LIVE_SEARCH_TESTS="1"; ...pytest -m live_search -s`, about 7 credits). Google does not always obey `site:`, so SerpAPI drops off-site results and the gateway falls back to Tavily. Tavily gives no publisher name (the skill uses the site host instead). A full live run passed on 2026-10-06 after fixing `strict_json_schema` (it deleted fields *named* `title`, so Groq never sent problem titles).
9. **Live run findings (Healthcare → Clinical AI, not yet fixed):** datasets step returned generic pages (data.gov home/about/metrics, zenodo.org home); government step returned healthcare.gov (insurance marketplace) instead of FDA/NIH/ARPA-H material; startups step found only one 2022 CB Insights list and confirmed none; an MDPI journal homepage was stored as a research paper; Scholar "organization" is the raw author/venue line (e.g. "DK Ryan, … - British Journal of …, 2024 - Wiley"); problem extraction takes ~50 s and 3 of 5 problems rest on one source.

10. **Second-hop startup matching is strict.** A startup counts as confirmed only if its name appears in the website address, so some real startups may be missed (fewer Tier A sources), but a wrong site is not marked official.

11. **Free search plans are small.** One research run uses about 12 searches (cap 15). When SerpAPI runs out, Grey switches to Tavily; when both run out, research shows "please try again".

12. **Release 0.5 has not been run with the real model yet.** Everything is tested with the fake LLM (and once end to end through a real server in fake mode). The first live run with Groq may need prompt tweaks. Fake-mode areas and designs are template-based (the "Sample data" badge shows when the evidence is mock data).

13. **The "named technology" check is a word list** (`SPECIFIC_TECHNOLOGIES` in `fyp_design_shared.py`). It catches common names (PyTorch, AWS, Kaggle, LSTM, …) but not every product; the prompt also tells the model not to name any.

14. **If the connection drops during a redesign**, the page shows the error but has no "Try again" for that redesign (the backend may still have saved it). Reloading the page doesn't restore the place yet (see item 3); `GET /projects/{id}/fyp-design` has the saved state.

15. **A failed redesign doesn't count** toward the 3-redesign limit; only saved redesigns do.

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
