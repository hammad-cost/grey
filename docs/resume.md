# Resume Checkpoint

**Updated:** 2026-10-06

| | |
|---|---|
| Current release | **0.4 — Real evidence**: Steps 1–6 and 8 done and committed together with 0.3; **Step 7 (live tests with real keys) pending** |
| Current step | 0.4 Step 7 — live tests. Waiting for the student to add `GROQ_API_KEY`, `SERPAPI_API_KEY`, `TAVILY_API_KEY` (+ `LLM_MODE=live`, `SEARCH_PROVIDERS=serpapi,tavily`) to `Backend/.env` and say "go". |
| Last completed step | 0.4 Step 8 — docs + full verification (567 backend + 1 skipped, 67 frontend, type-check clean, build OK) |
| Next action | When keys are in: check only that they are set (never print values), confirm with the student, add `tests/live/test_search_live.py` (skipped unless `RUN_LIVE_SEARCH_TESTS=1`), run it, then one full live run via the API (real search + Groq) and review steps/sources/problems with the student; fix what the live run reveals; commit; ask before pushing. The 0.3 browser walk-through is also still pending. |
| Last commit | "Release 0.3 + 0.4: problem opportunities and real-evidence search" on `main` (run `git log -1`). **Not pushed** — ask before pushing. |

## Release 0.4 plan — Real evidence (approved 2026-10-06)

| Step | What | Status |
|---|---|---|
| 1 | Search gateway: `SearchQuery.include_domains/recency_days`, `SearchResult.provider`, search error classes, `SearchGateway` (ordered fallback, retries, cooldowns), `SEARCH_PROVIDERS` setting (`mock` default; `mock` can't mix with real) | ✅ done |
| 2 | SerpAPI (google / tbm=nws / google_scholar, site: filters, tbs/as_ylo) + Tavily (topic, include_domains, time_range) adapters, `SERPAPI_API_KEY` / `TAVILY_API_KEY`, tests force `SEARCH_PROVIDERS=mock` | ✅ done |
| 3 | Editable site lists (`research_evidence/sources.py`) + exact-list rules before word clues (word clues use site name/publisher only, never headlines) + organization from Scholar venue / publisher / host + snippet cleaning (HTML, entities, leading dates) | ✅ done |
| 4 | Research plan v2: discover startups (YC, Product Hunt, F6S, Crunchbase/Dealroom public pages, StartupBlink) → confirm on startup websites (2nd hop, top ~5) → news → research papers (Scholar) → government → datasets; cap ~15 searches/run | ✅ done |
| 5 | Workflow/API touch-ups: `ResearchSummary.startups_confirmed` (sent in `research_completed.data.summary`), `by_category` includes news; startup warning when `SEARCH_PROVIDERS` names a provider without a key | ✅ done |
| 6 | Frontend: View sources shows source-type labels (`sourceTypeLabel`: Startup website vs Startup directory, News, Research paper, Government, …); research card describes the 6 steps and shows found-by-type (`startups_confirmed`, news, government, research, datasets); Sample data badge = fake LLM or `.example` sources | ✅ done |
| 7 ⏸ | Live tests (skipped by default) for SerpAPI + Tavily; one full live run (real search + Groq) with OK | ⬜ |
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
.\venv\Scripts\python.exe -m pytest -q      # expect 567 passed, 1 skipped
cd D:\Projects\Grey\Frontend
npm test                                    # expect 67 passed
cd D:\Projects\Grey
git status                                  # expect a clean tree
git log --oneline -3                        # newest should be "Release 0.3 + 0.4: …"
```
