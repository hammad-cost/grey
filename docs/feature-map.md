# Grey — Feature Map

**Last updated:** 2026-10-06 (Release 0.5)

For each feature, this map shows where it lives in every layer, from the button the student clicks to the database row, plus the tests that cover it.
Use it to find the right files before changing a feature.

Status key: ✅ implemented and tested · 🟡 partial · ⬜ not started

---

## Overview

| # | Feature | Status | Release |
|---|---|---|---|
| F1 | Start Project | ✅ | 0.1 |
| F2 | Industry Selection | ✅ | 0.1 |
| F3 | Branch Selection | ✅ | 0.1 |
| F4 | Project Brain persistence | ✅ (see limitations) | 0.1 |
| F5 | Workflow transition to `EVIDENCE_RESEARCH` | ✅ | 0.1 |
| F6 | Evidence Research (streamed progress) | ✅ 0.2; real search + six-step plan in 0.4 (live-tested; quality work paused after 0.4.1 Step 1) | 0.2 / 0.4 |
| F7 | Evidence read API | ✅ (no full-list UI; problem cards show their sources) | 0.2 |
| F8 | Problem Opportunities (find, show, choose) | ✅ (fake LLM by default; Groq when configured) | 0.3 |
| F9 | LLM gateway (profiles, fallback, providers) | ✅ (Fake + Groq) | 0.3 |
| F10 | Search gateway (SerpAPI → Tavily fallback) | ✅ (live-tested) | 0.4 / 0.4.1 |
| F11 | From problem to FYP (area, design, redesigns, approval) | ✅ (fake LLM by default; not yet run live) | 0.5 |

---

## Request flow (shared by F1–F3; F6, F8 and F11 stream — see F6, F8, F11)

```
Student clicks a button / card
  → domains/fyp/components/*            (UI)
  → useGreyActions()                    (core/grey-agent/hooks.ts)
  → fetch → FastAPI route               (Backend/app/api/projects.py)
      → validate input against taxonomy
      → LangGraph discovery graph       (resume the paused workflow)
      → WorkspaceBrainRepository        (save decision to Project Brain)
  ← GreyEvent JSON
  → GreyAgentProvider.applyEvent()      (updates GreyUIState)
  → page.tsx renders the component for the new stage
```

---

## F1 — Start Project

Creates a new FYP project, starts the Discovery workflow, and shows the industry choices.

| Layer | Detail |
|---|---|
| UI | "Start my FYP" button — `Frontend/app/page.tsx` (shown when `status === "idle"`) |
| Adapter action | `startProject()` — `Frontend/core/grey-agent/hooks.ts` |
| API | `POST /projects` → **201** — `Backend/app/api/projects.py::create_project` |
| Workflow | Graph starts with `thread_id = workspace_id`; pauses at `industry_selection` (`interrupt`) |
| Project Brain | New row: `workspace_id` (UUID), `workflow_state = INDUSTRY_SELECTION` |
| Event sent | `project_created` · stage `INDUSTRY_SELECTION` · status `awaiting_user` · `data.available_industries` (15) · allowed `selectIndustry`, `askGrey` |
| Tests | Backend: `tests/integration/test_projects_api.py` (create project tests), `tests/unit/test_brain.py`. Frontend: `core/grey-agent/GreyAgentProvider.test.tsx` ("keeps the latest event data…") |

---

## F2 — Industry Selection

The student picks one industry. It is validated, saved as approved, and the workflow moves on to branch selection.

| Layer | Detail |
|---|---|
| UI | `IndustrySelector` cards — `Frontend/domains/fyp/components/IndustrySelector.tsx` (rendered when stage is `INDUSTRY_SELECTION` and `selectIndustry` is allowed) |
| Data source | `eventData.available_industries` from the `project_created` event (not hardcoded in the UI) |
| Adapter action | `selectIndustry(industry)` |
| API | `POST /projects/{id}/industry` with `{"industry": "..."}` → **200**; **400** invalid industry; **404** unknown project; **422** missing field (FastAPI default, not covered by a test) |
| Workflow | Resumes `industry_selection` with the value; node validates it; graph pauses at `branch_selection` |
| Project Brain | `industry = <value>`, `industry_status = approved` |
| Event sent | `industry_saved` · stage `BRANCH_SELECTION` · `data.available_branches` · `brain_patch {industry, industry_status}` · allowed `selectBranch`, `askGrey` |
| Taxonomy | 15 industries — `Backend/app/domains/fyp/workflows/discovery/taxonomy.py` |
| Tests | Backend: `test_taxonomy.py`, `test_discovery_workflow.py`, `test_projects_api.py`. Frontend: `IndustrySelector.test.tsx` (6), adapter test "selectIndustry posts…" |

---

## F3 — Branch Selection

The student picks a branch within the chosen industry. It is validated against that industry, saved as approved, and the workflow pauses before evidence research.

| Layer | Detail |
|---|---|
| UI | `BranchSelector` cards — `Frontend/domains/fyp/components/BranchSelector.tsx` (rendered when stage is `BRANCH_SELECTION` and `selectBranch` is allowed). Heading names the chosen industry from `brainSummary.industry`. |
| Data source | `eventData.available_branches` from the `industry_saved` event |
| Adapter action | `selectBranch(branch)` |
| API | `POST /projects/{id}/branch` with `{"branch": "..."}` → **200**; **400** if no industry yet or branch not in that industry; **404** unknown project |
| Workflow | Resumes `branch_selection`; node validates; graph pauses **before** `evidence_research` (`interrupt_before`) |
| Project Brain | `branch = <value>`, `branch_status = approved`, `workflow_state = EVIDENCE_RESEARCH` |
| Event sent | `branch_saved` · stage `EVIDENCE_RESEARCH` · status `awaiting_user` · `brain_patch {branch, branch_status, workflow_state}` · allowed `startResearch` |
| Taxonomy | 80 branches, 5–7 per industry |
| Tests | Backend: `test_taxonomy.py`, `test_discovery_workflow.py`, `test_projects_api.py`. Frontend: `BranchSelector.test.tsx` (6), adapter test "selectBranch posts… finishes at EVIDENCE_RESEARCH" |

---

## F4 — Project Brain persistence

The durable source of truth for the student's accepted decisions. Chat history and CopilotKit state are not stored here.

| Layer | Detail |
|---|---|
| Table | `workspace_brain` — `Backend/app/core/brain/models.py` |
| Fields | `workspace_id`, `workflow_state`, `industry`, `industry_status`, `branch`, `branch_status`, `created_at`, `updated_at` |
| Read/write | `WorkspaceBrainRepository` only — `Backend/app/core/brain/repository.py`. Nothing else touches the database. |
| Read API | `GET /projects/{id}` → `WorkspaceBrainSnapshot` (**404** if unknown) |
| Database | `DATABASE_URL` (SQLite `grey.db` today; PostgreSQL/Supabase later with no code change) |
| Decision status values | `candidate`, `recommended`, `selected`, `approved`, `rejected`, `needs_revision` (only `approved` used so far) |
| Frontend mirror | `GreyUIState.brainSummary` (camelCase), built from each event's `brain_patch`. Display only — not the source of truth. |
| Research tables (0.2) | `research_run`, `evidence_source` — see F6/F7 |
| Tests | `tests/unit/test_brain.py` (8), `test_brain_evidence.py`, `test_projects_api.py` (full journey reads the Brain back) |
| Limitations | `workflow_state` is not updated after the industry step (stays `INDUSTRY_SELECTION` until the branch is saved). The frontend does not reload the Brain on page refresh. See `current-state.md` §5. |

---

## F5 — Workflow transition to `EVIDENCE_RESEARCH`

The workflow records that the project is ready for evidence research and waits for the student to start it (F6).

| Layer | Detail |
|---|---|
| Workflow | After `branch_selection` the graph pauses before `evidence_research` — `Backend/app/domains/fyp/workflows/discovery/graph.py` |
| Project Brain | `update_workflow_state(EVIDENCE_RESEARCH)` called by the branch route |
| Event | `branch_saved`, status `awaiting_user`, `allowed_actions: ["startResearch"]` |
| UI | `ResearchProgressCard` in its "ready" look: industry, branch and a **Start research** button (see F6) |
| Tests | `test_discovery_workflow.py::test_full_release_01_journey`, `test_projects_api.py::test_full_release_01_journey`, adapter full-journey test |
| Limitation | The paused workflow lives in memory (`MemorySaver`). After a backend restart, projects that were mid-journey cannot finish (branch step returns 500). See `current-state.md` §5. |

---

## F6 — Evidence Research (Release 0.2)

The student clicks **Start research**. Grey searches four categories, classifies each source (type + Tier A/B/C), saves the evidence to the Project Brain, and shows live progress while it works.

| Layer | Detail |
|---|---|
| UI | `ResearchProgressCard` — `Frontend/domains/fyp/components/ResearchProgressCard.tsx`. Looks: ready (Start research), running (checklist + "N sources found • M high-quality sources"), complete (summary by tier), failed (safe message + Try again). Also offers Try again if the connection drops mid-stream. |
| Data source | `eventData.steps`, `sources_found`, `high_quality_sources`, `summary`, `message` from the latest research event |
| Adapter action | `startResearch()` — `Frontend/core/grey-agent/hooks.ts`; reads the stream with `readEventStream()` — `core/grey-agent/stream.ts`; each event goes through `applyEvent()`; research events also set `GreyUIState.progress` |
| API | `POST /projects/{id}/research` → **200** streamed `application/x-ndjson` (one GreyEvent per line); **404** unknown project; **409** no branch yet / research already running — `Backend/app/api/research.py`. Opens its own DB session (`get_session_factory`) that stays open for the stream. |
| Runner | `start_evidence_research()` + `ResearchSession.events()` — `Backend/app/domains/fyp/workflows/discovery/research_runner.py`. Rebuilds the workflow position from the Brain after a restart; replaces runs orphaned by a stopped server. |
| Workflow | `evidence_research` node looks up the skill in the `SkillRegistry` and runs it — `nodes.py` |
| Skill | `ResearchEvidenceSkill` — `Backend/app/domains/fyp/skills/research_evidence/`. 5 searches over 4 categories, rule-based source type + tier, de-dup, max 5 per category, strongest first. No LLM. |
| Tool | `SearchProvider` interface + `MockSearchProvider` (`.example` URLs) — `Backend/app/core/tools/`. Chosen by `SEARCH_PROVIDER` (only `mock`); `MOCK_SEARCH_DELAY_MS` makes progress visible. |
| Startup | `register_skills()` in `Backend/main.py` registers FYP skills with the configured search provider |
| Project Brain | `research_run` row (running → complete/failed, counts, provider, error); `evidence_source` rows replaced on each successful run; failed runs keep earlier evidence |
| Events sent | `research_started` → (`searching_sources`, `sources_found`) ×4 → `evaluating_evidence` → `storing_evidence` → `research_completed` (status `complete`, allowed `extractProblems` (0.3), `data.summary`, `brain_patch {research_status, evidence_count, high_quality_evidence_count}`) — or `research_failed` (status `blocked`, safe `data.message`, allowed `startResearch`). Only step labels and counts are sent — never queries or raw errors. |
| Tests | Backend: `test_search_tool.py`, `test_evidence_classification.py`, `test_research_evidence_skill.py`, `test_research_workflow.py`, `test_brain_evidence.py`, `tests/integration/test_research_api.py`. Frontend: `stream.test.ts` (4), adapter `startResearch` tests (3), `ResearchProgressCard.test.tsx` (7) |

---

## F7 — Evidence read API (Release 0.2)

| Layer | Detail |
|---|---|
| API | `GET /projects/{id}/evidence` → `EvidenceListResponse {workspace_id, research, evidence[]}` (**404** if unknown) — `Backend/app/api/research.py`, `app/domains/fyp/schemas/responses.py` |
| Order | Tier A → C, then newest first, then title |
| Fields | title, organization, source_type, published_date, url, problem_addressed, relevant_insight, why_it_matters, evidence_tier, research_category, query, provider |
| UI | None yet — the card shows counts only. A source list is a candidate for the next release. |
| Tests | `tests/integration/test_research_api.py` (evidence tests) |

---

## F8 — Problem Opportunities (Release 0.3)

Right after research, Grey turns the stored evidence into 3–5 real, evidence-backed problems; the student must choose one (blueprint §12–15).

| Layer | Detail |
|---|---|
| UI | `ProblemProgressCard` (checklist; failure → Try again / Research again), `ProblemOptions` + `ProblemOpportunityCard` ×3–5 (task type, Tier badges, real-world problem, why it matters, FYP direction, **View sources** with link/organization/date/tier/supporting point, "Sample data" badge, confirm dialog), `SelectedProblemCard` — `Frontend/domains/fyp/components/` |
| Data source | `eventData.problems` (problem_options_ready), `eventData.problem` (problem_selected); parsed by `Frontend/domains/fyp/problems.ts` |
| Adapter actions | `startResearch()` continues into `/problems` automatically when research allows `extractProblems`; `extractProblems()` (retry); `selectProblem(id)` — `Frontend/core/grey-agent/hooks.ts` |
| API | `POST /projects/{id}/problems` → **200** NDJSON stream; **404** unknown; **409** research not complete / options exist / already running. `POST /projects/{id}/problem {problem_id}` → **200** `problem_selected`; **404**; **409** not choosing / not an option; **422** missing id. `GET /projects/{id}/problems` → `ProblemListResponse` — `Backend/app/api/problems.py` |
| Runner | `start_problem_extraction()` + `ProblemSession.events()`, `choose_problem()` — `Backend/app/domains/fyp/workflows/discovery/problem_runner.py`. Saves options with the workflow's ids; rebuilds the extraction position and the selection pause from the Brain after a restart. |
| Workflow | `problem_extraction` node (skill via registry; read-only evidence reader from the run config) → `problem_selection` node (`interrupt`, validates the id) — `nodes.py`, `graph.py` |
| Skill | `ProblemExtractionSkill` — `Backend/app/domains/fyp/skills/problem_extraction/`: `context.py` (≤20 strongest sources, refs `E1…`, no URLs/ids, ~2,500-token budget), `validation.py` (unknown ref, ungrounded, only Tier C, names an organization, URL, too long, duplicate), `skill.py` (one retry with feedback; `TooFewProblemsError` if <3; `NotEnoughEvidenceError` → LLM not called), `fake.py` (fake-mode answers). Prompt: `app/domains/fyp/prompts/problem_extraction.py` (`problem_extraction.v1`). |
| Project Brain | `problem_run` (status, research run used, provider, model, prompt version, drafts generated/kept, rejection counts, error), `problem_candidate` (options, rank, status `candidate`/`selected`), `problem_evidence` (problem ↔ evidence + supporting point). Stage → `PROBLEM_OPTIONS` then `PROBLEM_SELECTED`, in the same commit as the data. |
| Events | `problem_extraction_started` → `problem_extraction_progress` ×4 → `problem_options_ready` (stage `PROBLEM_OPTIONS`, `awaiting_user`, allowed `selectProblem`, `data.problems`, `data.summary`) — or `problem_extraction_failed` (`blocked`, safe message, allowed `extractProblems` or `startResearch`). Then `problem_selected` (stage `PROBLEM_SELECTED`, `complete`, allowed `designFYP` since 0.5 → F11). |
| Tests | Backend: `test_brain_problems.py`, `test_problem_extraction_skill.py`, `test_problem_workflow.py`, `tests/integration/test_problems_api.py`. Frontend: adapter tests (6 new), `ProblemOpportunityCard.test.tsx`, `ProblemOptions.test.tsx`, `ProblemProgressCard.test.tsx` |

---

## F9 — LLM gateway (Release 0.3)

| Layer | Detail |
|---|---|
| Skill-facing API | `LLMGateway.generate_structured(LLMRequest(skill, profile, instructions, input, output_schema, max_output_tokens))` → `LLMResult(output, provider, model, usage, attempts)` — `Backend/app/core/llm/` |
| Profiles | `fast_cheap`, `structured_reasoning`, `high_quality_reasoning`, `writing`, `long_context` — defaults in `profiles.py`; override per profile with `LLM_PROFILE_<NAME>=provider:model,…` |
| Routing / fallback | `router.py` (skip providers without a key, unavailable or cooling down, or too small); `gateway.py` (retry with backoff / retry-after, total deadline, one repair, fallback rules); `health.py` (per-provider unavailable, per-model cooldown) |
| Errors | `errors.py`: rate limited, timeout, server error, quota exhausted, auth error, context too long, invalid output, refusal (never falls back), bad request, unavailable |
| Providers | `FakeLLMProvider` (scripts + responders; default), `OpenAICompatibleProvider` (httpx; configured as `groq`) — `providers/` |
| Configuration | `LLM_MODE=fake|live`, `GROQ_API_KEY`, `GROQ_BASE_URL`, `LLM_TIMEOUT_SECONDS`, `LLM_TOTAL_DEADLINE_SECONDS`, `LLM_MAX_RETRIES`, `LLM_COOLDOWN_SECONDS`, `LLM_QUOTA_COOLDOWN_SECONDS` — `config.py`, `settings.py`, `.env.example` |
| Logging | One `grey.llm` log line per attempt: skill, profile, provider, model, outcome, tokens, latency. Never prompts, input or keys. |
| Tests | `test_llm_gateway.py`, `test_llm_providers.py` (fake HTTP transport), `test_llm_config.py`; live: `tests/live/test_groq_live.py` (skipped unless `RUN_LIVE_LLM_TESTS=1`) |

---

## F10 — Real evidence: search gateway and research plan v2 (Release 0.4)

| Layer | Detail |
|---|---|
| Research plan | Six steps — `discover_startups` (startup directories, Tier C) → `confirm_startups` (second hop: own website, Tier A) → `industry_news` → `government` (2 searches) → `research_papers` (Scholar) → `datasets` — `Backend/app/domains/fyp/skills/research_evidence/queries.py`, `skill.py` |
| Second hop | Names from directory titles ("Harbor AI \| Y Combinator" → "Harbor AI"); `"<name>" <branch>`; own site = name in the web address and not a listed directory/news/research/government/social site — `startups.py` |
| Site lists | Startup directories, trusted news, peer-reviewed publishers, preprints, government endings, international bodies, data portals, community datasets, social/blogs — **edit `sources.py`** |
| Classification | List checks first, then word clues from site name/publisher only; organization from Scholar venue / publisher / host; snippet cleaning — `classification.py` |
| Search gateway | `SearchGateway`: order from `SEARCH_PROVIDERS`; retries (backoff, retry-after); fallback on rate limit / timeout / server error (after retries), out of credits, bad key, bad request, no results; rest periods; `SearchUnavailable` when all fail; logs without query text — `Backend/app/core/tools/search_gateway.py` |
| Adapters | `SerpApiProvider` (google / tbm=nws / google_scholar, `site:` filters, tbs / as_ylo) and `TavilySearchProvider` (topic, include_domains, time_range) — `Backend/app/core/tools/providers/` |
| Settings | `SEARCH_PROVIDERS` (`mock` default; `serpapi,tavily`; mock can't be mixed with real), `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `RESEARCH_MAX_SEARCHES` (15), `SEARCH_TIMEOUT_SECONDS`, `SEARCH_MAX_RETRIES`, `SEARCH_COOLDOWN_SECONDS`, `SEARCH_QUOTA_COOLDOWN_SECONDS`; startup warning if a listed provider has no key |
| Events / UI | Checklist ids = step ids; `research_completed.data.summary` adds `startups_confirmed` and `by_category.news`; research card shows found-by-type; View sources shows source-type labels — `research_events.py`, `ResearchProgressCard.tsx`, `ProblemOpportunityCard.tsx`, `problems.ts` |
| Tests | `test_search_gateway.py`, `test_search_providers.py`, `test_startup_discovery.py`, `test_evidence_classification.py` (real sites), `test_research_evidence_skill.py` (second hop, budget); frontend `problems.test.ts`, card tests. Live: `tests/live/test_search_live.py` (`-m live_search`, skipped unless `RUN_LIVE_SEARCH_TESTS=1`). 0.4.1 Step 1: `SearchProvider.keeps_to_sites()` (Tavily first for site-limited searches), `GOVERNMENT_SEARCH_SITES`, `STARTUP_PROFILE_SITES`, 10 results per search (20 for discovery). |

---

## F11 — From problem to FYP (Release 0.5)

After the student confirms a problem, Grey works out where it sits (functional area, specific area), designs a student-sized FYP, explains "Why this FYP?" from stored evidence, and the student approves it or asks for up to 3 controlled redesigns (blueprint §16–18).

| Layer | Detail |
|---|---|
| UI | `FunctionalAreaCard` (Industry → Branch → Functional area → Specific area → Problem + explanation), `FYPDirectionCard` (live checklist; failure → Try again; review: title, what you'll build, who uses it, input, output, main contribution, **Why this FYP?** with sources and links, **Approve this FYP** with confirm dialog, **Adjust** with 4 radio options + optional note ≤200 chars + "N of 3 redesigns left", version badge), `ApprovedFYPCard` — `Frontend/domains/fyp/components/`; `SelectedProblemCard` stays visible while the design starts |
| Data source | `eventData.fyp` (fyp_direction_ready, fyp_design_failed after a redesign, fyp_direction_approved), `eventData.area` (area_classified), `brainSummary` (`functionalArea`, `specificArea`, `fypTitle`, …); parsed by `Frontend/domains/fyp/fypDesign.ts` |
| Adapter actions | `selectProblem(id)` continues into `/fyp-design` automatically when the backend allows `designFYP`; `designFYP()` (retry); `adjustFYPDirection(adjustment, note?)`; `approveFYPDirection(designId)` — `Frontend/core/grey-agent/hooks.ts` |
| API | `POST /projects/{id}/fyp-design` → **200** NDJSON stream; **404** unknown; **409** no problem chosen / already designed / already running. `POST /projects/{id}/fyp-design/adjust {adjustment, note?}` → **200** stream; **409** no draft / 3 redesigns used / running; **422** not a controlled option or note too long. `POST /projects/{id}/fyp-design/approve {design_id}` → **200** `fyp_direction_approved`; **409** not the current draft / no draft / redesign running. `GET /projects/{id}/fyp-design` → `FYPDesignResponse` (area, current design, Why this FYP?, redesigns used/left, latest run) — `Backend/app/api/fyp_design.py` |
| Runner | `start_fyp_design()`, `start_fyp_redesign()` + `FYPDesignSession.events()`, `approve_fyp()` — `Backend/app/domains/fyp/workflows/fyp_design/runner.py`. Saves the area as soon as it's classified (a retry then skips it), saves each design version with the workflow's id, fails runs left "running", rebuilds the review pause from the Brain before every redesign/approval. |
| Workflow | Separate graph `fyp_design`: `area_classification` → `fyp_design` → `fyp_review` (`interrupt`: approve → END, adjust → `fyp_design`; validates the controlled option and the limit) — `nodes.py`, `graph.py`, `state.py` |
| Skills | `classify_area` (`fast_cheap`) and `design_fyp` (`structured_reasoning`) — `Backend/app/domains/fyp/skills/classify_area/`, `design_fyp/`; shared `ProblemBrief`, progress and text checks in `fyp_design_shared.py`. Checks: link, organization name, named technology/dataset/model/API (word list), too long, area = branch, specific = functional, unchanged redesign; one retry. Prompts `classify_area.v1`, `design_fyp.v1` with `ADJUSTMENT_REQUESTS` — `app/domains/fyp/prompts/`. Fake-mode answers in each skill's `fake.py`. |
| Why this FYP? | Built by code in `workflows/fyp_design/view.py` from the selected problem (real-world problem, why it matters, observed solutions, cited sources with supporting points) + the design's `scope_reduction` |
| Project Brain | `functional_area` (one per project), `fyp_design_run` (kind initial/adjustment, adjustment, note, status, provider/model/prompt version, error), `fyp_design` (version, status draft/superseded/approved, fields, adjustment, note, approved_at). Stages `PROBLEM_SELECTED` → `AREA_CLASSIFICATION` → `FYP_DESIGN` → `APPROVED_FYP`, each in the same commit as its data. Max 3 saved redesigns. |
| Events | `fyp_design_started` → `fyp_design_progress` (classifying) → `area_classified` → `fyp_design_progress` ×3 (designing, checking, saving) → `fyp_direction_ready` (stage `FYP_DESIGN`, `awaiting_user`, allowed `approveFYPDirection` + `adjustFYPDirection` while redesigns are left, `data.fyp`). Redesign: started → progress ×3 → ready. Failure: `fyp_design_failed` — first design: `blocked`, allowed `designFYP`; redesign: `awaiting_user`, current design kept, allowed approve/adjust. Approval: `fyp_direction_approved` (stage `APPROVED_FYP`, `complete`, no actions). |
| Tests | Backend: `test_brain_fyp_design.py` (26), `test_fyp_design_skills.py` (36), `test_fyp_design_workflow.py` (24), `tests/integration/test_fyp_design_api.py` (13). Frontend: adapter tests (7 new), `fypDesign.test.ts`, `FunctionalAreaCard.test.tsx`, `FYPDirectionCard.test.tsx`, `ApprovedFYPCard.test.tsx` |
