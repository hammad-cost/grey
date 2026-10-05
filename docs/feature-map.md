# Grey — Feature Map

**Last updated:** 2026-10-05 (Release 0.2)

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
| F6 | Evidence Research (streamed progress) | ✅ (mock search provider) | 0.2 |
| F7 | Evidence read API | ✅ (no UI list yet) | 0.2 |

---

## Request flow (shared by F1–F3; F6 streams — see F6)

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
| Events sent | `research_started` → (`searching_sources`, `sources_found`) ×4 → `evaluating_evidence` → `storing_evidence` → `research_completed` (status `complete`, `data.summary`, `brain_patch {research_status, evidence_count, high_quality_evidence_count}`) — or `research_failed` (status `blocked`, safe `data.message`, allowed `startResearch`). Only step labels and counts are sent — never queries or raw errors. |
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
