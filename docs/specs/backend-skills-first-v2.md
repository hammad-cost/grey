Grey Backend Blueprint
Skills-first, modular backend architecture for Grey MVP and future AI companion platform
Implementation Handoff • Version 2.0 • Workflows → Skills → Tools → Workspace Brain

# 1. Purpose and Architecture Decision
This document supersedes Backend Blueprint v1.0. The architecture keeps the same core decisions—FastAPI, LangGraph, PostgreSQL/Supabase, explicit HITL, provider abstractions—but simplifies the reusable AI layer. The previous term “capability” is replaced by “skill.”
The implementation model to lock is:
WORKFLOW = what should happen and in what order
SKILL    = what Grey knows how to do
TOOL     = what a skill can use
BRAIN    = what Grey knows and what has been accepted/decided
- Grey remains a structured product, not an unrestricted chatbot.
- Project/Workspace Brain in PostgreSQL is the persistent source of truth.
- LangGraph controls workflows, interrupts, routing and runtime state.
- Skills implement reusable intelligent tasks; skills do not own the journey.
- Tools are low-level integrations such as search, academic APIs, dataset APIs, web fetch and model providers.
- CopilotKit is the interaction bridge; it never owns authoritative project state.
- The MVP begins with one Grey agent. A skill may later be replaced by a specialized agent without changing its external contract.
- Do not implement speculative startup/student domains now. Build extension points only where they are cheap and obvious.
# 2. Locked Technology Direction

# 3. System Architecture
Student / CopilotKit UI
│
▼
FastAPI / Grey API Gateway
│
▼
Grey Orchestrator
│
▼
LangGraph Workflow Router
┌────┼────────────┬─────────────┐
▼    ▼            ▼             ▼
Discovery  FYP Design  Technical   Validation / Proposal
Workflow   Workflow    Planning    Workflows
│          │           │             │
└──────────┴─────┬─────┴─────────────┘
▼
SKILLS
│
▼
TOOLS
│
┌───────────┼────────────┐
▼           ▼            ▼
LLMs      External APIs   Workspace Brain
PostgreSQL
# 4. Core Vocabulary

# 5. Workspace Brain: Persistent Source of Truth
For the FYP MVP, the user-facing term may remain “Project Brain.” Internally, prefer the more generic “Workspace Brain” abstraction so future workspace types can reuse the same core infrastructure. Do not over-generalize the database prematurely; only the service/repository boundary needs to be generic now.
- Chat history is discussion history, not authoritative state.
- LangGraph state is execution state, not the durable project database.
- Recommendations are not decisions until accepted by workflow/HITL logic.
- If old conversation conflicts with an approved Brain decision, the Brain wins until explicitly changed.
## 5.1 Decision status model
candidate → recommended → selected → approved
↘ rejected
↘ needs_revision
## 5.2 FYP MVP Brain groups

# 6. Workflow Architecture
Workflows determine sequencing, allowed transitions, mandatory pauses, and which skill is invoked. Keep workflows readable and deterministic where possible. Do not place full prompts, provider calls, or large business logic directly in graph nodes.

## 6.1 Mandatory interrupts
- Industry selection
- Branch selection
- Problem selection
- FYP direction approval
- Final scope approval
- Consequential dataset selection
- High-impact upstream change
- Final proposal readiness
# 7. Skills Architecture
A skill is the main reusable intelligent unit. Every skill should be callable from a workflow, a test, or—later—a specialized agent. Skills must not assume which screen is open or what should happen next.
## 7.1 Skill contract
Skill metadata
- name
- description
- input schema
- output schema
- allowed tools
- model/cost policy
- requires human approval? (normally false; workflow decides)
- version

Skill implementation
- validate input
- load only required Brain context
- call tools / LLM gateway
- validate structured output
- return result
- do NOT silently approve major decisions
## 7.2 Initial FYP skills

# 8. Skill Registry
Create a small registry so workflows and future agents invoke skills through a consistent contract. The registry should not become a dynamic plugin platform in the MVP; it is simply a centralized catalog and lookup layer.
SkillRegistry
research_evidence        -> ResearchEvidenceSkill
extract_problems         -> ExtractProblemsSkill
find_datasets            -> FindDatasetsSkill
design_architecture      -> DesignArchitectureSkill
assess_feasibility       -> AssessFeasibilitySkill
generate_proposal        -> GenerateProposalSkill
Benefits: discoverability, consistent logging, cost attribution, simpler testing, versioning, and an easy future path from skill → specialist agent.
# 9. Tools and Provider Interfaces
Tools are narrow operations. Skills own task-level reasoning; tools do not know the student journey.
SearchProvider.search(query, filters) -> SearchResult[]
WebFetchProvider.fetch(url) -> SourceDocument
AcademicSearchProvider.search(query) -> AcademicResult[]
DatasetSearchProvider.search(query, task) -> DatasetResult[]
ModelSearchProvider.search(task, constraints) -> ModelResult[]
LLMGateway.generate_structured(task, input, schema, policy) -> typed result
WorkspaceBrainRepository.get_snapshot(workspace_id) -> WorkspaceBrainSnapshot
WorkspaceBrainRepository.apply_decision(...) -> Decision
# 10. LLM Gateway and Token Economics
- No provider SDK calls scattered through skills or workflows.
- Load only core Grey rules + current skill instructions + relevant Brain subset + required evidence.
- Do not resend entire conversation history by default.
- Use structured outputs with Pydantic validation.
- Route cheap extraction/classification to lower-cost models and complex synthesis/reasoning to stronger models.
- Log skill name, model, tokens, latency, workspace ID and success/failure for cost analysis.
- Prompts are versioned per skill, not embedded in graph nodes.
# 11. Grey Agent Today; Multi-Agent Tomorrow
MVP: one Grey agent executes controlled workflows and invokes registered skills. Do not create a research agent, technical agent, writing agent, etc. until complexity justifies them.
MVP
Grey Agent
├── research_evidence skill
├── find_datasets skill
├── design_architecture skill
└── generate_proposal skill

Future (only when justified)
Grey Supervisor Agent
├── Research Agent     (same external research skill contract)
├── Technical Agent    (same technical skill contracts)
└── Writing Agent      (same proposal skill contract)
The key migration rule: a specialist agent must preserve the same typed input/output contract as the skill it replaces. Workflows and frontend events therefore do not need a rewrite.
# 12. Future Domain Expansion Without a Rewrite
FYP is the first Grey domain. Later, Grey may support Startup, Research, or broader Student journeys. The codebase should separate Grey Core from domain-specific modules, but only FYP modules are implemented now.
backend/
app/
core/
orchestrator/
workflow_runtime/
brain/
skills_registry/
tools/
llm/
events/
auth/
domains/
fyp/
workflows/
skills/
schemas/
prompts/
# future only when needed:
# startup/
# research/
# student/
## 12.1 Shared vs domain skills

Do not generalize a skill merely because it might be reusable someday. Promote it to core only after real reuse appears.
# 13. API, Actions and Events
The frontend invokes explicit product actions. Free conversation is allowed, but authoritative state changes must map to validated actions.
Actions
startProject
selectIndustry
selectBranch
selectProblem
approveFYPDirection
modifyScope
selectDataset
approveTechnicalPlan
goBack
askGrey
generateProposal

Event envelope
{
"type": "problem_options_ready",
"workspace_id": "w_123",
"domain": "fyp",
"workflow": "discovery",
"stage": "PROBLEM_OPTIONS",
"status": "awaiting_user",
"data": {...},
"brain_patch": {...},
"allowed_actions": ["selectProblem", "requestMoreProblems", "askGrey"]
}
# 14. Change-Impact Rules
Industry / Branch
→ Evidence
→ Problem
→ Functional Area
→ FYP Design
→ Scope
→ AI Strategy / Dataset
→ Stack / Architecture / Evaluation
→ Feasibility
→ Proposal
Changing an upstream approved decision must produce an impact preview, preserve reusable evidence where possible, and mark dependent decisions as stale/needs_revision instead of blindly deleting everything.
# 15. Recommended Repository Structure
backend/
app/
api/                    # thin FastAPI routes
core/
orchestrator/         # GreyOrchestrator + domain routing
workflow_runtime/     # LangGraph integration helpers
brain/                # generic Workspace Brain interface/repository
skills/               # registry, base protocol, shared skills if truly shared
tools/                # provider interfaces + adapters
llm/                  # gateway + provider adapters
events/               # event schemas + dispatcher
config/
domains/
fyp/
workflows/
discovery/
fyp_design/
technical_planning/
validation/
proposal/
skills/
research_evidence/
extract_problems/
find_datasets/
design_architecture/
feasibility/
proposal_generation/
...
schemas/
prompts/
main.py
tests/
unit/
integration/
workflows/
# 16. MVP Build Sequence
- Foundation: repository, FastAPI, PostgreSQL/Supabase, migrations, Workspace/Project Brain models, auth/project identity.
- Skill foundation: Skill protocol + registry + LLM gateway + tool interfaces. Use mocks initially.
- LangGraph skeleton: Main FYP router + Discovery workflow with deterministic industry/branch transitions.
- Vertical Slice 1: Start → Industry → Branch persisted end-to-end with CopilotKit actions/events.
- Vertical Slice 2: research_evidence skill + progress streaming + evidence persistence.
- Vertical Slice 3: extract_problems skill + cards + mandatory selection interrupt.
- Vertical Slice 4: FYP design and scope skills + approval.
- Vertical Slice 5: technical skills (AI need, datasets, stack, architecture, evaluation).
- Vertical Slice 6: feasibility and supervisor-readiness skills.
- Vertical Slice 7: proposal generation + consistency validation from approved Brain state.
# 17. Guardrails for Claude / Coding Agents
- Do not build a giant universal LangGraph.
- Do not turn every skill into an autonomous agent.
- Do not let a skill own workflow transitions.
- Do not store authoritative decisions only in chat or CopilotKit state.
- Do not make frontend components depend on a specific LLM or internal agent topology.
- Do not over-generalize FYP code into a generic platform before real reuse exists.
- Do not duplicate tools inside each skill; use provider interfaces.
- Do not add startup/student domains until they are being implemented.
- Prefer one small, typed skill with tests over one large prompt.
- Every new feature should ideally be added as a workflow step, a skill, a tool, or a UI component—not a cross-cutting rewrite.
# 18. Final Architecture Statement
Grey uses workflows to guide journeys, skills to perform intelligent tasks, tools to access external systems, and the Workspace Brain to remember accepted decisions.
This design supports the current FYP MVP, a future full student companion, startup-building journeys, and eventual multi-agent orchestration without forcing a rewrite of the frontend, persistence model, or workflow contracts.