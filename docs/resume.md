# Resume Checkpoint

**Updated:** 2026-10-05

| | |
|---|---|
| Current release | 0.2 — Evidence Research |
| Current step | 5 — API + startup integration (not started) |
| Last completed step | 4 — Workflow integration (verified: 237 backend tests passing) |
| Next action | Add `POST /projects/{id}/research` (streams research events) and `GET /projects/{id}/evidence`; register FYP skills at startup in `main.py`; branch event gets `allowed_actions: ["startResearch"]`; route opens its own DB session for the stream. |
| Last commit | "Release 0.2 (WIP): Steps 1–4" on `main` (run `git log -1` for the hash). Everything up to Step 4 is committed. |

## Release 0.2 plan

| Step | What | Status |
|---|---|---|
| 1 | Brain: `research_run` + `evidence_source` storage | ✅ done |
| 2 | Search tool interface + mock provider | ✅ done |
| 3 | `ResearchEvidenceSkill` + tier classification + registry | ✅ done |
| 4 | Workflow: research node via registry, progress events, restart recovery | ✅ done |
| 5 | API: research stream route, evidence route, startup registration | ⏭ next |
| 6 | Frontend adapter: `startResearch` + stream reader | ⬜ |
| 7 | `ResearchProgressCard` + page | ⬜ |
| 8 | Docs + full verification + commit | ⬜ |

## Decisions already made (do not re-ask)
- Mock search provider only; no real vendor until the 0.2 architecture is verified.
- Streaming progress (not "all at the end").
- Event names: `research_started`, `searching_sources`, `sources_found`, `evaluating_evidence`, `storing_evidence`, `research_completed` (+ `research_failed`).
- Evidence fields `problem_addressed`, `relevant_insight`, `why_it_matters` are required.
- No LLM calls, no problem extraction, no dataset recommendation in 0.2.
- Frontend tests: Vitest only (no Playwright/Cypress/Jest).

## How to verify the last good state
```powershell
cd D:\Projects\Grey\Backend
.\venv\Scripts\python.exe -m pytest -q      # expect 237 passed
cd D:\Projects\Grey
git status                                  # expect a clean tree, or only Step 5+ work in progress
git log --oneline -3                        # newest should be "Release 0.2 (WIP): Steps 1–4"
```
