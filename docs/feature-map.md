# Grey — Feature Map

**Last updated:** 2026-10-05 (Release 0.1)

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

---

## Request flow (shared by F1–F3)

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

The student picks a branch within the chosen industry. It is validated against that industry, saved as approved, and the workflow finishes Release 0.1.

| Layer | Detail |
|---|---|
| UI | `BranchSelector` cards — `Frontend/domains/fyp/components/BranchSelector.tsx` (rendered when stage is `BRANCH_SELECTION` and `selectBranch` is allowed). Heading names the chosen industry from `brainSummary.industry`. |
| Data source | `eventData.available_branches` from the `industry_saved` event |
| Adapter action | `selectBranch(branch)` |
| API | `POST /projects/{id}/branch` with `{"branch": "..."}` → **200**; **400** if no industry yet or branch not in that industry; **404** unknown project |
| Workflow | Resumes `branch_selection`; node validates; runs `evidence_research`; graph reaches END |
| Project Brain | `branch = <value>`, `branch_status = approved`, `workflow_state = EVIDENCE_RESEARCH` |
| Event sent | `branch_saved` · stage `EVIDENCE_RESEARCH` · status `complete` · `brain_patch {branch, branch_status, workflow_state}` · allowed actions: none |
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
| Tests | `tests/unit/test_brain.py` (8), `test_projects_api.py` (full journey reads the Brain back) |
| Limitations | `workflow_state` is not updated after the industry step (stays `INDUSTRY_SELECTION` until the branch is saved). The frontend does not reload the Brain on page refresh. See `current-state.md` §5. |

---

## F5 — Workflow transition to `EVIDENCE_RESEARCH`

The end point of Release 0.1. The workflow records that the project is ready for evidence research and stops.

| Layer | Detail |
|---|---|
| Workflow | `evidence_research_node` sets `workflow_state = EVIDENCE_RESEARCH` and the graph ends — `Backend/app/domains/fyp/workflows/discovery/nodes.py`, `graph.py` |
| Project Brain | `update_workflow_state(EVIDENCE_RESEARCH)` called by the branch route |
| Event | `branch_saved`, status `complete`, `allowed_actions: []` (nothing more the student can do) |
| UI | Green "Release 0.1 complete — Grey is ready to research evidence" box with industry and branch — `Frontend/app/page.tsx` |
| Not included | No research is performed. No skills or LLM calls run. |
| Tests | `test_discovery_workflow.py::test_full_release_01_journey`, `test_projects_api.py::test_full_release_01_journey`, adapter full-journey test |
| Limitation | The paused workflow lives in memory (`MemorySaver`). After a backend restart, projects that were mid-journey cannot finish (branch step returns 500). See `current-state.md` §5. |
