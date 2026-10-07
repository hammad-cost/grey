# Resume Checkpoint

**Updated:** 2026-10-07

| | |
|---|---|
| Current release | **0.6 — Project definition and scope: COMPLETE** (all 7 steps, local commits `1a18121` … Step 7 docs commit). **Not pushed, not tagged** — the student reviews first. Do NOT start 0.7. |
| Current step | Waiting for the student's review of Release 0.6 (and 0.5, also unreviewed). |
| Last completed step | 0.6 Step 7 — docs + full verification: 744 backend passing + 10 skipped (live), 129 frontend, type-check clean, build OK; fake-mode end-to-end run through a real server (… → approve FYP → definition → moves → 4th move refused 409 → approve scope → SCOPE_APPROVED → late move refused 409). |
| Next action | Student reviews. Optional next: (a) one live run of 0.5 + 0.6 with Groq (ask first; ~3–7 Groq calls), (b) browser walk-through of 0.3–0.6, (c) "push to GitHub", (d) resume 0.4.1 Step 2 (evidence quality), (e) plan 0.7 (AI necessity check + AI/ML strategy, blueprint §22–23) — only when asked. |
| Last commit | Release 0.6 Step 7 docs commit on `main` (run `git log --oneline -10`). Unpushed commits since `origin/main`: 0.3+0.4, 0.4 Step 7, 0.4.1 Step 1, 0.5 Steps 1–7, 0.6 Steps 1–7. **Ask before pushing.** |

## Release 0.6 plan — Project definition and scope (2026-10-07; built in one continuous run at the student's request: "do 0.6 in single shot")

Scope chosen from the product blueprint's stage order (`APPROVED_FYP → SCOPE → …`): blueprint Steps 10–12 (§19 Problem Definition, §20 Scope Definition, §21 Proposed Solution).
Boundary: `APPROVED_FYP → (define) → SCOPE (review: move features) → SCOPE_APPROVED`.
Not in 0.6: AI necessity check / AI strategy (§22–23, next), datasets, models, stack, hardware, architecture, evaluation, feasibility, proposal.

| Step | What | Commit |
|---|---|---|
| 1 | Brain: `project_definition_run`, `project_definition` (problem definition + proposed solution JSON), `scope_item`; stage `SCOPE_APPROVED`; `scope_rules.py` (Core 2–8, moves); repository + snapshot fields | ✅ `1a18121` |
| 2 | Skill `define_project` (structured_reasoning) via registry + gateway; prompt `define_project.v1`; checks (sizes, links, org names, named tech, duplicates, length); fake answer | ✅ `d7dc8de` |
| 3 | `project_definition` LangGraph workflow (define → scope_review interrupt: move ↺ / approve → END), runner (restart-safe), events, view; `fyp_direction_approved` allows `defineProject` | ✅ `8dbc64e` |
| 4 | API: `POST /project-definition` (stream), `POST /scope/move`, `POST /scope/approve`, `GET /project-definition` | ✅ `9710b63` |
| 5 | Frontend adapter: `defineProject`, `moveScopeItem`, `approveScope`; auto-define after `approveFYPDirection` | ✅ `6e6176e` |
| 6 | `ProjectDefinitionCard`, `ApprovedScopeCard`; `projectDefinition.ts` | ✅ `1065ab2` |
| 7 | Docs + full verification | ✅ (docs commit) |

0.6 decisions (made by Claude while building in one go — the student may revisit):
- Scope changes are **moves only** between Core / Optional / Out of scope (no typing new features, no AI rewrite of the definition). Core must keep **2–8** features; the rule lives in one place (`app/core/brain/scope_rules.py`) used by both the workflow and the repository; the frontend mirrors it only to disable buttons.
- Grey asks the model for 3–6 core, 1–4 optional, 2–5 out of scope, 2–6 modules, 3–8 workflow steps.
- The proposed solution shows target user / input / output **from the approved design** (not regenerated). The blueprint's "AI component / non-AI components" (§21) is left to the AI necessity check (0.7) so AI is never forced in early.
- Review happens at the existing stage `SCOPE`; new stage `SCOPE_APPROVED` ends 0.6 (like `APPROVED_FYP` ended 0.5).
- The definition starts automatically after the student approves the FYP (same pattern as 0.3 and 0.5).
- No limit on the number of moves; approval needs a confirm click.

## Release 0.5 plan — From problem to FYP (approved 2026-10-06; built in one continuous run)

Boundary: `PROBLEM_SELECTED → AREA_CLASSIFICATION → FYP_DESIGN → review (≤3 controlled redesigns) → APPROVED_FYP`.
Not in 0.5: scope, AI necessity/strategy, datasets, models, stack, architecture, evaluation, feasibility, proposal.

| Step | What | Commit |
|---|---|---|
| 1 | Brain: `functional_area`, `fyp_design_run`, `fyp_design` (versions draft/superseded/approved), stage `APPROVED_FYP`, repository + limits, snapshot fields | ✅ `27e317f` |
| 2 | Skills `classify_area` (fast_cheap) + `design_fyp` (structured_reasoning) via registry + gateway; prompts; checks (no links / org names / named tech; unchanged redesign); fake answers | ✅ `8a5a03d` |
| 3 | `fyp_design` LangGraph workflow (area → design → review interrupt → END or redesign), runner (restart-safe), events, "Why this FYP?" view; `problem_selected` allows `designFYP` | ✅ `c86859a` |
| 4 | API: `POST /fyp-design` (stream), `POST /fyp-design/adjust` (stream), `POST /fyp-design/approve`, `GET /fyp-design` | ✅ `bce0a6a` |
| 5 | Frontend adapter: `designFYP`, `adjustFYPDirection`, `approveFYPDirection`; auto-design after `selectProblem` | ✅ `53da182` |
| 6 | `FunctionalAreaCard`, `FYPDirectionCard`, `ApprovedFYPCard`; `fypDesign.ts` | ✅ `496bfa2` |
| 7 | Docs + full verification | ✅ (docs commit) |

0.5 decisions: adjustments are exactly `make_simpler`, `change_target_user`, `change_system_focus`, `reduce_complexity` (no "more AI") + optional note ≤200 chars; max 3 saved redesigns (failed ones don't count); the design never names a dataset/model/API/stack; "Why this FYP?" is built by code from stored evidence; approval needs a confirm click.

## Release 0.4.1 plan — Evidence quality (approved 2026-10-06; PAUSED after Step 1, `2708b85`)

Live run (Healthcare → Clinical AI) findings are in current-state.md item 9.

| Step | What | Status |
|---|---|---|
| 1 ✅ | Site-limited searches ask providers that keep to the sites first (`SearchProvider.keeps_to_sites(query)`: Tavily yes; SerpAPI only for Scholar/RESEARCH); government step limited to `GOVERNMENT_SEARCH_SITES`; discovery searches only `STARTUP_PROFILE_SITES`; `RESULTS_PER_SEARCH=10`, `DISCOVERY_RESULTS=20`; 2 live tests | done (startup live re-check not run) |
| 2 | Topic + step-fit filters in research_evidence (no AI): result must mention the branch phrase or a main branch word; drop home/about pages (except a startup's own site); each step keeps only its kind (government / datasets / research); drop same-title duplicates (EU page came back in 2 languages) | ⬜ |
| 3 | Labels: news-step results from unlisted sites → News Tier C; Scholar organization = venue, or publisher when the venue is cut short ("…") or the last part has spaces | ⬜ |
| 4 | Live check: re-run Healthcare → Clinical AI (~15 searches + Groq), compare before/after; docs; commit (no push) | ⬜ |

Out of scope for 0.4.1: ≥2 sources per problem, problem-finding speed (~50 s) — judge after Step 4.

## Release 0.4 plan — Real evidence (approved 2026-10-06)

| Step | What | Status |
|---|---|---|
| 1 | Search gateway: `SearchQuery.include_domains/recency_days`, `SearchResult.provider`, search error classes, `SearchGateway` (ordered fallback, retries, cooldowns), `SEARCH_PROVIDERS` setting (`mock` default; `mock` can't mix with real) | ✅ done |
| 2 | SerpAPI (google / tbm=nws / google_scholar, site: filters, tbs/as_ylo) + Tavily (topic, include_domains, time_range) adapters, `SERPAPI_API_KEY` / `TAVILY_API_KEY`, tests force `SEARCH_PROVIDERS=mock` | ✅ done |
| 3 | Editable site lists (`research_evidence/sources.py`) + exact-list rules before word clues (word clues use site name/publisher only, never headlines) + organization from Scholar venue / publisher / host + snippet cleaning (HTML, entities, leading dates) | ✅ done |
| 4 | Research plan v2: discover startups (YC, Product Hunt, F6S, Crunchbase/Dealroom public pages, StartupBlink) → confirm on startup websites (2nd hop, top ~5) → news → research papers (Scholar) → government → datasets; cap ~15 searches/run | ✅ done |
| 5 | Workflow/API touch-ups: `ResearchSummary.startups_confirmed` (sent in `research_completed.data.summary`), `by_category` includes news; startup warning when `SEARCH_PROVIDERS` names a provider without a key | ✅ done |
| 6 | Frontend: View sources shows source-type labels (`sourceTypeLabel`: Startup website vs Startup directory, News, Research paper, Government, …); research card describes the 6 steps and shows found-by-type (`startups_confirmed`, news, government, research, datasets); Sample data badge = fake LLM or `.example` sources | ✅ done |
| 7 | Live tests (skipped by default) for SerpAPI + Tavily; one full live run (real search + Groq) with OK | ✅ done 2026-10-06 (`38c2b9d`) |
| 8 | Docs (`current-state.md` §0a, `architecture.md` search path, `feature-map.md` F10), all checks, local commit of 0.3 + 0.4 | ✅ done (not pushed) |

Research plan v2 (Step 4): steps `discover_startups` → `confirm_startups` (2nd hop: `startups.py` names from directory titles, own site = host contains the squashed name and isn't a listed/gov site → STARTUP Tier A) → `industry_news` (new `ResearchCategory.NEWS`) → `government` (2 queries) → `research_papers` (SerpAPI Scholar ignores site filters) → `datasets`. `ResearchProgress.step` drives the checklist. Budget `RESEARCH_MAX_SEARCHES=15`; the 2nd hop only uses what's left after reserving later steps; max 5 startups.

0.4 decisions: SerpAPI first, Tavily fallback; **global** search; arXiv = Tier B, peer-reviewed = Tier A, government = Tier A, startup's own site = Tier A, directories = Tier C, reputable news = Tier B; ~15 searches per run (configurable); live mode never falls back to mock; no scraping of YC/Dealroom directly (search engines only); Dealroom/Crunchbase paid APIs later/optional. The student puts `SERPAPI_API_KEY` / `TAVILY_API_KEY` / `GROQ_API_KEY` in `Backend/.env` themselves — never ask to paste keys in chat. The 0.3 browser walk-through is still pending (student may do it any time).

## Release 0.3 plan (approved 2026-10-05) — all steps done, uncommitted

| Step | What | Status |
|---|---|---|
| 1 | Brain: `problem_run`, `problem_candidate`, `problem_evidence` + repository methods | ✅ done |
| 2 | LLM layer (gateway, profiles, router, fallback, health, validation, logging) + Fake + Groq providers | ✅ done |
| 3 | `ProblemExtractionSkill` (profile `structured_reasoning`): load evidence via `EvidenceReader`, call gateway, validate/ground, dedup, rank → typed `ProblemCandidate`s; no DB writes | ✅ done |
| 4 | Workflow: `problem_extraction` + `problem_selection` (interrupt) nodes; runner saves results; restart-safe HITL | ✅ done |
| 5 | API: `POST /projects/{id}/problems` (stream), `POST /projects/{id}/problem`, `GET /projects/{id}/problems` | ✅ done |
| 6 | Frontend adapter: `extractProblems()` auto after `research_completed`; `selectProblem(id)` | ✅ done |
| 7 | `ProblemOpportunityCard` ×3–5, View sources, confirm step, selected-problem summary | ✅ done |
| 8 | Docs + full verification (live Groq run and commit deferred to the end of 0.4) | ✅ done |

**Work rhythm (0.3, 0.4):** stop after each step and wait for the student's "go".

## Decisions already made (do not re-ask)

From 0.2:
- Mock search provider only; no real search vendor yet.
- Streaming progress; stream = one GreyEvent JSON per line (`application/x-ndjson`). Errors before streaming → 404/409; failures during → a `*_failed` event.
- Evidence fields `problem_addressed`, `relevant_insight`, `why_it_matters` are required.
- Frontend tests: Vitest only (no Playwright/Cypress/Jest).

For 0.3:
- **Responsibilities:** tools/repositories retrieve and store facts; the LLM only reasons. The LLM never writes to the DB and never does web research. API routes never call the LLM. Skills go through the Skill Registry.
- **The runner persists** problem candidates (the skill returns typed `ProblemCandidate`s, no DB writes). The skill reads evidence only through a read-only `EvidenceReader`.
- **Problem extraction starts automatically** after research completes (the frontend calls it).
- **Multi-provider LLM design:** Grey-owned `LLMGateway`; provider adapters; skills request a **profile** (`fast_cheap`, `structured_reasoning`, `high_quality_reasoning`, `writing`, `long_context`), never a provider/model. ProblemExtractionSkill uses `structured_reasoning`.
- **Fallback rules:** 429/timeout/5xx → retry then fallback; quota → fallback; invalid key → mark unavailable + fallback; malformed output → repair then fallback; context too long → only to a larger-context route; **safety refusal → NO fallback** (Anthropic server-side `fallbacks` stays off).
- **Providers:** Groq is the only real provider in 0.3 (the student will have a Groq key); Anthropic/OpenAI deferred. Groq via one httpx-based `OpenAICompatibleProvider` (no new dependency; httpx moves to main requirements). Models (from Groq docs, 2026-10-05): `structured_reasoning` = `groq:openai/gpt-oss-120b` → `groq:openai/gpt-oss-20b` (both production, strict JSON schema, 131K context). Free tier: 8K tokens/min, 200K tokens/day per model. The student puts `GROQ_API_KEY` in `Backend/.env` themselves — never ask them to paste it in chat.
- `LLM_MODE=fake` by default. `tests/conftest.py` forces fake mode for every test run. The one live test (`tests/live/test_groq_live.py`) is skipped unless `RUN_LIVE_LLM_TESTS=1` — run only with the student's OK.
- Keep compatible with a future LiteLLM adapter; no skill depends on LiteLLM.
- Problem validation is deterministic code: refs must exist, supporting points must be grounded in the source text, ≥1 Tier A/B source, no copied organization names, no URLs in text, dedup, rank, keep top 5, fail (never pad) if <3.
- Skill details: context = strongest ≤20 sources, texts ≤300 chars, ≈2,500-token budget, refs E1…En, no URLs/ids/queries; `max_output_tokens=4000`; prompt in `app/domains/fyp/prompts/problem_extraction.py` (`problem_extraction.v1`). Source-based dedup only when both problems cite ≥2 sources (sharing one source is normal). Fake mode: `install_fake_answers()` registers a pattern-based responder.
- Workflow (Step 4): graph = … → evidence_research → ⏸ → problem_extraction → problem_selection (interrupt) → END. The node assigns candidate ids (uuid) and the runner saves with the same ids (`complete_problem_run(candidate_ids=…)`), so selection is checked against the Brain. The repository reaches the skill only as `configurable["evidence_reader"]` (never stored in state). `research_completed` now allows `extractProblems`. New events: `problem_extraction_started/_progress/_failed`, `problem_options_ready`, `problem_selected`. Failure → `problem_extraction_failed` (allows `extractProblems`, or `startResearch` when evidence is too thin). `choose_problem` rebuilds the selection pause from the Brain after a restart.
- API (Step 5): `POST /projects/{id}/problems` (NDJSON; 404 / 409), `POST /projects/{id}/problem {problem_id}` (404 / 409 / 422), `GET /projects/{id}/problems` (`ProblemListResponse`). The problems route gives the skill a `SessionEvidenceReader` (own short session + `asyncio.shield`) — fixes a real bug where closing the tab mid-read left SQLite locked.
- Frontend adapter (Step 6): `startResearch()` streams research, then automatically streams `/problems` when `research_completed` allows `extractProblems` (inside the same loading state — no useEffect). `extractProblems()` = retry. `selectProblem(id)`. Shared `runEventStream()` helper. Adapter state has `lastEventType`, so cards know whose `eventData` it is.
- UI (Step 7): `ResearchProgressCard` shrinks to a one-line summary once `problem_*` events arrive; `ProblemProgressCard` (checklist; failure → Try again / Research again); `ProblemOptions` (3–5 `ProblemOpportunityCard`s, "Sample data" badge for fake LLM or `.example` sources, confirm dialog before `selectProblem`); `SelectedProblemCard`. Shared `StepChecklist`; problem parsing in `domains/fyp/problems.ts`.
- The selected problem is stored as `status = selected` on its candidate (no change to existing tables). Research can't replace evidence once problem options exist. `complete_problem_run` moves the project to `PROBLEM_OPTIONS` and `select_problem` to `PROBLEM_SELECTED` in the same commit as the data.

## How to verify the last good state
```powershell
cd D:\Projects\Grey\Backend
.\venv\Scripts\python.exe -m pytest -q      # expect 744 passed, 10 skipped
cd D:\Projects\Grey\Frontend
npm test                                    # expect 129 passed
cd D:\Projects\Grey
git status                                  # expect a clean tree
git log --oneline -3                        # newest should be "Release 0.6 Step 7: …"
```
