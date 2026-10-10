# Grey — Architecture (as built)

**Last updated:** 2026-10-10 (Release 0.7)

This describes the architecture that **actually exists in the code**.
The target architecture is defined in `docs/specs/` (backend and frontend blueprints v2). Where the two differ, see §6.

---

## 1. Big picture

```
┌──────────────────────── Frontend (Next.js, :3000) ─────────────────────────┐
│ app/page.tsx  ── picks a component by GreyUIState.currentStage              │
│   └ domains/fyp/components/  IndustrySelector, BranchSelector,             │
│                              ResearchProgressCard, ProblemProgressCard,    │
│                              ProblemOptions, SelectedProblemCard,          │
│                              FunctionalAreaCard, FYPDirectionCard,         │
│                              ApprovedFYPCard                               │
│        └ core/grey-agent/    Grey UI Adapter (provider + hooks + stream)   │
│              useGreyActions() ── fetch() ──────────────┐                    │
└────────────────────────────────────────────────────────┼────────────────────┘
                              HTTP + JSON, NDJSON stream │ (CORS)
┌──────────────────────── Backend (FastAPI, :8000) ──────▼────────────────────┐
│ app/api/projects.py, research.py, problems.py, fyp_design.py,             │
│         project_definition.py                         thin routes         │
│   ├ app/domains/fyp/workflows/discovery/   LangGraph Discovery graph        │
│   │     (MemorySaver checkpointer, thread_id = workspace_id)                │
│   │     ├ research_runner.py  runs evidence_research, yields GreyEvents     │
│   │     └ problem_runner.py   runs problem_extraction, applies the choice   │
│   ├ app/domains/fyp/workflows/fyp_design/  LangGraph FYP Design graph (0.5) │
│   │     └ runner.py  area → design → review (approve / ≤3 redesigns)        │
│   ├ app/domains/fyp/workflows/project_definition/  graph (0.6)              │
│   │     └ runner.py  define → scope review (move features / approve)        │
│   ├ app/core/skills/     SkillRegistry ← ResearchEvidenceSkill,             │
│   │                                      ProblemExtractionSkill,            │
│   │                                      ClassifyAreaSkill, DesignFYPSkill, │
│   │                                      DefineProjectSkill                 │
│   │     ├ app/core/tools/  SearchGateway → SerpAPI / Tavily (or Mock)      │
│   │     └ app/core/llm/    LLMGateway → router → Fake / Groq providers     │
│   ├ app/core/brain/      WorkspaceBrainRepository → SQLAlchemy → SQLite     │
│   │                      (skills only get a read-only EvidenceReader)       │
│   └ app/core/events/     GreyEvent envelope                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend layout

```
Backend/
├── main.py                         FastAPI app, CORS, routers; on startup: create tables, register skills
└── app/
    ├── api/projects.py             discovery routes (thin)
    ├── api/research.py             research stream + evidence routes (thin)
    ├── api/problems.py             problem stream + selection + listing routes (thin)
    ├── api/fyp_design.py           FYP design stream, redesign stream, approval, read (thin, 0.5)
    ├── api/project_definition.py   definition stream, scope move, scope approval, read (thin, 0.6)
    ├── api/ai_strategy.py          AI check stream, re-check stream, approval, read (thin, 0.7)
    ├── core/                       shared, domain-independent
    │   ├── config/                 Settings from .env
    │   ├── brain/                  Project Brain: model, schemas, repository, database, readers,
    │   │                           scope_rules.py (Core 2–8 features, moves; plain code)
    │   ├── events/                 GreyEvent envelope + enums
    │   ├── skills/                 Skill base class + SkillRegistry
    │   ├── tools/                  SearchProvider interface, SearchGateway (fallback), factory,
    │   │                           providers/: mock_search, serpapi, tavily, common helpers
    │   └── llm/                    LLM gateway: profiles, router, health, errors, providers/
    └── domains/fyp/                FYP-specific code
        ├── schemas/                request + response bodies
        ├── prompts/                versioned prompts (problem_extraction.py, classify_area.py, design_fyp.py,
        │                           define_project.py)
        ├── skills/research_evidence/  ResearchEvidenceSkill: research plan (queries.py), site lists
        │                              (sources.py), classification rules, second hop (startups.py)
        ├── skills/problem_extraction/ ProblemExtractionSkill: context, validation, fake answers
        ├── skills/classify_area/   ClassifyAreaSkill: functional + specific area (0.5)
        ├── skills/design_fyp/      DesignFYPSkill: student-sized FYP, controlled redesigns, checks (0.5)
        ├── skills/fyp_design_shared.py  ProblemBrief, progress, text checks shared by the 0.5/0.6 skills
        ├── skills/define_project/  DefineProjectSkill: problem definition, scope, proposed solution, checks (0.6)
        ├── skills/plan_ai_strategy/ PlanAIStrategySkill: AI necessity verdict, task, approach, checks (0.7)
        ├── workflows/discovery/    state, nodes, graph, taxonomy, research/problem runners + events
        ├── workflows/fyp_design/   state, nodes, graph, runner, events, view ("Why this FYP?") (0.5)
        ├── workflows/project_definition/  state, nodes, graph, runner, events, view (0.6)
        └── workflows/ai_strategy/  state, nodes, graph, runner, events, view (0.7)
```

**Responsibilities**

| Part | Owns | Does not |
|---|---|---|
| Route (`api/`) | Input validation, HTTP errors (400/404), calling workflow + repository, building the `GreyEvent` | Business rules beyond validation |
| Workflow (`domains/fyp/workflows/discovery/`) | Stage order, pausing for student input (`interrupt`), validating choices | Touching the database, deciding UI |
| Repository (`core/brain/repository.py`) | All reads/writes of Project Brain | Workflow logic |
| Taxonomy (`taxonomy.py`) | The fixed industry/branch lists | — (deterministic data, no AI) |
| Research runner (`research_runner.py`) | Checking research may start, recording the run, streaming the graph's progress as events | Research logic |
| Problem runner (`problem_runner.py`) | Checking extraction may start, recording the run, saving options and the choice, rebuilding the HITL pause after a restart | Problem logic, calling the LLM |
| FYP design runner (`workflows/fyp_design/runner.py`) | Checking a design / redesign / approval may happen, recording each run, saving the area, each design version and the approval, rebuilding the review pause from the Brain before every step | Area or design logic, calling the LLM |
| Project definition runner (`workflows/project_definition/runner.py`) | Checking the definition / a move / approval may happen, recording each run, saving the definition with the workflow's ids, checking a move against the scope rules before resuming, rebuilding the review pause from the Brain | Definition logic, calling the LLM |
| Scope rules (`core/brain/scope_rules.py`) | Whether a move is allowed (Core 2–8) and where the item lands; used by both the workflow and the repository | — (deterministic, no AI) |
| Skill (`domains/fyp/skills/`) | Research: searching, classifying, ranking evidence. Problems: choosing context, asking the LLM, checking/merging/ranking drafts | Writing to the database, HTTP, choosing a model |
| Tool (`core/tools/`) | Talking to search providers; ordered fallback, retries, rest periods (`SearchGateway`) | Knowing about students, workflows or evidence tiers |
| LLM gateway (`core/llm/`) | Picking a model from a profile, retries, fallback, cooldowns, schema validation, logging | Knowing about FYPs, prompts, or the database |

**One request, step by step** (e.g. select industry):
1. Route checks the industry is in the taxonomy (400 if not) and the project exists (404 if not).
2. Route resumes the graph: `graph.ainvoke(Command(resume=industry), thread_id=workspace_id)`.
3. Node validates again, updates execution state, graph pauses at the next `interrupt`.
4. Route calls `repo.apply_decision(workspace_id, "industry", value)` → saved as `approved`.
5. Route returns a `GreyEvent` describing the new stage and allowed actions.

---

### Search path (Release 0.4)

```
ResearchEvidenceSkill  (6 steps, budget RESEARCH_MAX_SEARCHES)
  1 discover startups   SearchQuery(focus=COMPANIES, include_domains=startup directories)
  2 confirm startups    names from directory titles → '"<name>" <branch>' → own website (Tier A)
  3 industry news       focus=NEWS
  4 government          focus=GOVERNMENT ×2
  5 research papers     focus=RESEARCH  (SerpAPI → Google Scholar)
  6 datasets            focus=DATASETS, include_domains=data portals
  → SearchGateway (SEARCH_PROVIDERS order, e.g. serpapi,tavily)
      per search: retry short failures → rest the provider → next provider
      out of credits / bad key → next provider at once; no results → next provider too
      all failed → SearchUnavailable → research_failed (never falls back to mock)
  → classification (sources.py lists first, then word clues) → EvidenceSource
→ research runner saves the evidence
```

### LLM call path (Release 0.3)

```
ProblemExtractionSkill
  → LLMRequest(profile="structured_reasoning", instructions, input, output_schema)
  → LLMGateway.generate_structured()
      → router: profile routes, minus providers without a key / unavailable / cooling down / too small
      → for each route: provider.generate_json()  (retry short failures, 1 repair for bad JSON)
      → fallback to the next route on rate limit / timeout / 5xx / quota / bad key / context too long
      → STOP on safety refusal or bad request (never sent to another model)
      → Pydantic-validated output + provider/model/usage/attempts
  → skill's own checks (grounding, refs, tiers, names, URLs, duplicates) → 3–5 ProblemCandidates
→ problem runner saves them (the LLM never touches the database)
```

### FYP design path (Release 0.5)

```
selectProblem → problem_selected (allows designFYP) → adapter POSTs /fyp-design
  runner: check stage, claim project, fail leftover run, position the graph
  fyp_design graph
    area_classification  → ClassifyAreaSkill (fast_cheap) → runner saves functional_area
                            (stage AREA_CLASSIFICATION) → area_classified event
    fyp_design           → DesignFYPSkill (structured_reasoning) → checks → runner saves
                            version 1 (stage FYP_DESIGN) → fyp_direction_ready
    fyp_review           ⏸ interrupt
      adjust (≤3)  → POST /fyp-design/adjust → Command(resume=adjust) → fyp_design again
                     → new version, previous draft superseded
      approve      → POST /fyp-design/approve → Command(resume=approve) → END
                     → stage APPROVED_FYP
  "Why this FYP?" = code over the stored problem + its cited evidence + design.scope_reduction
```

### Project definition path (Release 0.6)

```
approveFYPDirection → fyp_direction_approved (allows defineProject) → adapter POSTs /project-definition
  runner: check stage APPROVED_FYP, claim project, fail leftover run
  project_definition graph
    define_project  → DefineProjectSkill (structured_reasoning) → checks → node gives ids
                      → runner saves definition + scope items (stage SCOPE) → project_definition_ready
    scope_review    ⏸ interrupt
      move     → POST /scope/move {item_id, to} → scope_rules check → Command(resume=move)
                 → scope_review again → repository saves the move → scope_updated
      approve  → POST /scope/approve {definition_id} → Command(resume=approve) → END
                 → stage SCOPE_APPROVED → scope_approved
  target user / input / output shown with the definition come from the approved design (view.py)
```

### AI strategy path (Release 0.7)

```
approveScope → scope_approved (allows checkAINeed) → adapter POSTs /ai-strategy
  runner: check stage SCOPE_APPROVED, claim project, fail leftover run
  ai_strategy graph
    plan_ai_strategy → PlanAIStrategySkill (structured_reasoning) → checks + ai_strategy_rules
                       → runner saves the strategy (stage AI_STRATEGY) → ai_strategy_ready
    strategy_review  ⏸ interrupt
      recheck (≤2) → POST /ai-strategy/recheck {preference} → recheck rules → Command(resume=recheck)
                     → plan_ai_strategy again (sees the preference + previous answer)
                     → repository replaces the draft, rechecks_used + 1 → ai_strategy_ready
      approve      → POST /ai-strategy/approve {strategy_id} → Command(resume=approve) → END
                     → stage AI_STRATEGY_APPROVED → ai_strategy_approved
  which re-checks are offered = view.py, using the same rules as the repository
```

### Dataset path (Release 0.8)

```
approveAIStrategy → ai_strategy_approved (allows findDatasets) → adapter POSTs /datasets
  runner: check stage AI_STRATEGY_APPROVED, claim project, fail leftover run
  dataset_discovery graph
    find_datasets → FindDatasetsSkill
                    search.py: 4 targeted searches → SearchGateway → keep dataset pages only (max 8)
                    model (structured_reasoning) picks primary + alternative BY PAGE NUMBER
                    validation.py + dataset_rules (found links only, facts from the snippet, …)
                  → runner saves the plan + the pages found (stage DATASET_DISCOVERY) → dataset_options_ready
    dataset_review ⏸ interrupt
      research (≤2) → POST /datasets/research {preference} → research rules → Command(resume=research)
                      other_options: 3 new searches, pages shown before skipped
                      own_data:      no searches, pages found before reused, own data becomes primary
                    → repository replaces the draft, researches_used + 1 → dataset_options_ready
      select        → POST /datasets/select {plan_id, choice} → Command(resume=select) → END
                    → stage DATASET_SELECTED → dataset_selected
  which re-searches are offered = view.py, using the same rules as the repository
```

## 3. Two kinds of state

| | Project Brain | LangGraph state |
|---|---|---|
| Purpose | Accepted decisions — **source of truth** | Where the workflow is paused |
| Stored in | Database (`workspace_brain`, `research_run`, `evidence_source`, `problem_run`, `problem_candidate`, `problem_evidence`, `functional_area`, `fyp_design_run`, `fyp_design`, `project_definition_run`, `project_definition`, `scope_item`, `ai_strategy_run`, `ai_strategy`) | `MemorySaver` (process memory), one per graph (discovery, fyp_design, project_definition, ai_strategy) |
| Survives restart | Yes | **No** (research, problem extraction, selection, every FYP design step and every project definition step rebuild their position from the Brain) |
| Written by | API route via repository | LangGraph |

The frontend's `GreyUIState` is a third, display-only copy. It is rebuilt from events and is never treated as truth.

---

## 4. Frontend layout

```
Frontend/
├── app/                    layout.tsx (shell + provider), page.tsx (stage → component)
├── core/grey-agent/        Grey UI Adapter — the only place that talks to the backend
│   ├── types.ts            GreyUIState, GreyEvent, Actions
│   ├── GreyAgentProvider   holds state; applyEvent(); maps brain_patch → brainSummary
│   ├── hooks.ts            useGreyUIState, useGreyAgent, useGreyActions (fetch calls)
│   ├── stream.ts           readEventStream(): reads one GreyEvent per line from a streamed response
│   └── index.ts            public exports — components import only from here
├── domains/fyp/components/ IndustrySelector, BranchSelector, ResearchProgressCard, ProblemProgressCard,
│                           ProblemOptions, ProblemOpportunityCard, SelectedProblemCard, StepChecklist,
│                           FunctionalAreaCard, FYPDirectionCard, ApprovedFYPCard (0.5),
│                           ProjectDefinitionCard, ApprovedScopeCard (0.6),
│                           AIStrategyCard, ApprovedAIStrategyCard (0.7)
├── domains/fyp/problems.ts reads problem options from event data safely
├── domains/fyp/fypDesign.ts reads the area / FYP design / Why this FYP from event data safely (0.5)
├── domains/fyp/projectDefinition.ts reads the definition + scope, mirrors the core limits (0.6)
└── domains/fyp/aiStrategy.ts reads the AI strategy, turns verdict / task / approach values into words (0.7)
```

**Rules in force**
- Product components import from `@/core/grey-agent` only — never from CopilotKit or `fetch` directly.
- What to render is decided by `currentStage` **and** `allowedActions` from the latest backend event.
- Option lists (industries, branches, problems) and checklists come from `eventData`, never hardcoded in the UI.
- `lastEventType` tells a card whether the latest `eventData` belongs to it (research vs problems vs FYP design).

---

## 5. Contract between frontend and backend

Every state-changing response is a `GreyEvent`:

```json
{
  "type": "industry_saved",
  "workspace_id": "…",
  "domain": "fyp",
  "workflow": "discovery",
  "stage": "BRANCH_SELECTION",
  "status": "awaiting_user",
  "data": { "industry": "Finance", "available_branches": ["Banking", "…"] },
  "brain_patch": { "industry": "Finance", "industry_status": "approved" },
  "allowed_actions": ["selectBranch", "askGrey"]
}
```

- Backend uses **snake_case**; the adapter converts `brain_patch` keys to camelCase (`industryStatus`, `branchStatus`, `workflowState`).
- Transport: plain HTTP `POST`/`GET`, one request → one event — except `POST /projects/{id}/research`, `POST /projects/{id}/problems`, `POST /projects/{id}/fyp-design`, `POST /projects/{id}/fyp-design/adjust`, `POST /projects/{id}/project-definition`, `POST /projects/{id}/ai-strategy` and `POST /projects/{id}/ai-strategy/recheck`, which stream many events as newline-delimited JSON (`application/x-ndjson`). Errors before a stream starts are HTTP errors (404/409/422); failures during it arrive as a `research_failed` / `problem_extraction_failed` / `fyp_design_failed` / `project_definition_failed` / `ai_strategy_failed` event.
- After `research_completed` (which allows `extractProblems`) the adapter immediately calls `/problems`; after `problem_selected` (which allows `designFYP`) it immediately calls `/fyp-design`; after `fyp_direction_approved` (which allows `defineProject`) it immediately calls `/project-definition` — so the student doesn't click twice.
- CORS origins come from `CORS_ORIGINS` in `Backend/.env`.

---

## 6. Differences from the blueprints (`docs/specs/`)

| Blueprint says | Built in 0.1 | Why / next step |
|---|---|---|
| CopilotKit handles agent interaction, shared state, actions, streaming | CopilotKit **installed but not wired**. The Grey adapter calls FastAPI with `fetch`. | No AI or chat in 0.1. The adapter's hooks are the seam where CopilotKit plugs in later without changing components. |
| Workflows run through an orchestrator using skills | Routes call the graph (or the research runner) directly. The `evidence_research` node uses the first skill, `research_evidence`, via the `SkillRegistry`. | Industry/branch are deterministic. No separate orchestrator yet. |
| Streaming via CopilotKit | Research progress streams over a plain `fetch` + NDJSON reader in the adapter | Same events, no CopilotKit runtime needed yet. |
| LLM calls behind a gateway | `LLMGateway` with profiles and provider adapters; only Groq is wired as a real provider; fake mode is the default | Other providers (Anthropic, OpenAI, LiteLLM) are one adapter each. |
| Real web / academic search | SerpAPI + Tavily behind `SearchGateway`; mock by default | Live-tested 2026-10-06. Adding a vendor = one adapter in `core/tools/providers/` + one entry in the factory. |
| One workflow per stage (Discovery, FYP Design, …) | `discovery`, `fyp_design`, `project_definition` and `ai_strategy` are separate graphs, each with its own checkpointer | Later stages (datasets, technical planning, …) get their own graphs the same way. |
| Startup databases (Dealroom, Crunchbase) | Public pages found via search only | Paid APIs are optional, later. |
| Durable workflow execution | `MemorySaver` (in-memory) checkpointer | Simple for 0.1. A persistent checkpointer is needed before real use (see `current-state.md` §5). |
| PostgreSQL / Supabase | SQLite via `DATABASE_URL` | Swappable by config; no migrations tool yet (`create_all` at startup). |
| — | Backend CORS middleware | Added because the browser calls the API directly from another port. |

---

## 7. Testing setup

| | Tool | Location | Notes |
|---|---|---|---|
| Backend | pytest + pytest-asyncio + httpx | `Backend/tests/unit`, `Backend/tests/integration`, `Backend/tests/live` | Integration tests (`tests/integration/conftest.py`) use in-memory SQLite, a fresh `MemorySaver`, and their own skill registry with a no-delay mock search and a fake-mode LLM gateway. `tests/conftest.py` forces `LLM_MODE=fake` and `SEARCH_PROVIDERS=mock` for every run. Search adapters are tested against `httpx.MockTransport`. `tests/live/` calls Groq (marker `live_llm`) only when `RUN_LIVE_LLM_TESTS=1`, and SerpAPI/Tavily (marker `live_search`) only when `RUN_LIVE_SEARCH_TESTS=1`. |
| Frontend | Vitest 5 + jsdom + Testing Library | `*.test.tsx` next to the code | Config: `Frontend/vitest.config.mts`. Component tests mock `@/core/grey-agent`; adapter tests fake only `fetch`. No browser end-to-end tool (by decision). |
