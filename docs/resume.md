# Resume Checkpoint

**Updated:** 2026-10-05

| | |
|---|---|
| Current release | 0.2 — Evidence Research (**all 8 steps done**) |
| Current step | None — Release 0.2 is complete. Waiting for the student to walk through it in the browser. |
| Last completed step | 8 — Docs + full verification (251 backend, 29 frontend tests, type-check, build OK; real-server stream + CORS checked) |
| Next action | Manual browser walk-through (Start my FYP → industry → branch → Start research). Then choose Release 0.3 scope (e.g. evidence source list UI, problem extraction, persistent checkpointer). Do not start 0.3 without approval. |
| Last commit | "Release 0.2: evidence research with streamed progress" on `main` (run `git log -1`). Not pushed. |

## Release 0.2 plan

| Step | What | Status |
|---|---|---|
| 1 | Brain: `research_run` + `evidence_source` storage | ✅ done |
| 2 | Search tool interface + mock provider | ✅ done |
| 3 | `ResearchEvidenceSkill` + tier classification + registry | ✅ done |
| 4 | Workflow: research node via registry, progress events, restart recovery | ✅ done |
| 5 | API: research stream route (NDJSON), evidence route, startup registration | ✅ done |
| 6 | Frontend adapter: `startResearch` + stream reader | ✅ done |
| 7 | `ResearchProgressCard` + page | ✅ done |
| 8 | Docs + full verification + commit | ✅ done |

## Decisions already made (do not re-ask)
- Mock search provider only; no real vendor until the 0.2 architecture is verified.
- Streaming progress (not "all at the end").
- Event names: `research_started`, `searching_sources`, `sources_found`, `evaluating_evidence`, `storing_evidence`, `research_completed` (+ `research_failed`).
- Evidence fields `problem_addressed`, `relevant_insight`, `why_it_matters` are required.
- No LLM calls, no problem extraction, no dataset recommendation in 0.2.
- Frontend tests: Vitest only (no Playwright/Cypress/Jest).
- Stream format: one GreyEvent JSON per line (`application/x-ndjson`). Errors before streaming → 404/409; failures during → `research_failed` event.
- `branch_saved` now has status `awaiting_user` and `allowed_actions: ["startResearch"]`.

## How to verify the last good state
```powershell
cd D:\Projects\Grey\Backend
.\venv\Scripts\python.exe -m pytest -q      # expect 251 passed
cd D:\Projects\Grey
cd Frontend; npm test                       # expect 29 passed
cd D:\Projects\Grey
git status                                  # expect a clean tree
git log --oneline -3                        # newest should be "Release 0.2: evidence research with streamed progress"
```
