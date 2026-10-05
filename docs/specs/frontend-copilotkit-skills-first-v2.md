Grey Frontend & CopilotKit Blueprint
Conversation-first agent UI connected to workflows, skills, HITL and the Workspace Brain
Implementation Handoff • Version 2.0 • Frontend remains stable as backend evolves from one agent to many

# 1. Frontend Product Goal
This document supersedes Frontend & CopilotKit Blueprint v1.0. The user experience remains intentionally simple: a familiar conversation-first interface with contextual cards, dialogs, drawers and approvals. The backend is now described as Workflows → Skills → Tools → Workspace Brain, but this change must not make the frontend more complex.
- The student should see one obvious next action at a time.
- Chat is the primary surface; structured UI appears only when useful.
- The sidebar contains projects/workspaces, Project Brain, evidence, proposal and future modules.
- Human-in-the-loop is central: Grey pauses at meaningful decisions.
- Frontend does not care whether a result came from one Grey agent, a skill, or a future specialist agent.
- Backend events and typed action contracts are the stable boundary.
# 2. Connection to the Backend
Student
│
▼
Next.js / React
│
▼
Grey UI Adapter (our abstraction)
│
▼
CopilotKit / AG-UI
│
▼
Grey Orchestrator + LangGraph Workflows
│
▼
Skills
│
▼
Tools
│
▼
Workspace Brain (PostgreSQL)
The UI communicates in terms of Grey actions, Grey events, and projected UI state. It must never import or depend on internal skill classes, LangGraph node names, model providers, or future multi-agent topology.
# 3. Locked Frontend Stack

# 4. CopilotKit: What It Is in Grey
CopilotKit is the interaction bridge between the React application and Grey’s agent runtime. It is not the backend, not the database, and not the product architecture.

# 5. CopilotKit Adapter Boundary
To avoid coupling the entire product to a specific UI framework, create a small Grey-specific adapter layer. Product components should prefer Grey abstractions rather than importing CopilotKit everywhere.
Example frontend abstraction

<GreyAgentProvider>
useGreyAgent()
useGreyUIState()
useGreyActions()
<GreyActionRenderer />

Internally today:
Grey adapter → CopilotKit

Future:
If CopilotKit APIs change, most product components remain untouched.
# 6. Default Application Shell
┌──────────────────────────────────────────────────────┐
│ Grey                                  Project / Profile │
├──────────────┬───────────────────────────────────────┤
│ Collapsible  │                                       │
│ Sidebar      │          Conversation                 │
│              │                                       │
│ + New FYP    │ Grey message                          │
│ My Projects  │                                       │
│ Current FYP  │ Contextual UI appears only when       │
│ Project Brain│ the workflow/agent needs it           │
│ Evidence     │                                       │
│ Proposal     │                                       │
├──────────────┴───────────────────────────────────────┤
│ Ask Grey...                                    Send │
└──────────────────────────────────────────────────────┘
The sidebar is secondary navigation. The main FYP journey must be completable from the conversation surface and contextual components.
# 7. UX Philosophy
- Progressive disclosure: never show advanced functionality before it is needed.
- Use chat for explanation; use cards/buttons/forms for decisions.
- Do not show a permanent enterprise dashboard on first launch.
- Project Brain and evidence are inspectable but hidden by default.
- Show safe activity/progress, never private chain-of-thought.
- Allow contextual questions without losing workflow state.
- Allow backward changes, but show dependency impact before confirmation.
- Desktop-first for deep planning; mobile can focus on conversation, review and quick approvals initially.
# 8. Stable Frontend State Contract
type GreyUIState = {
workspaceId: string | null
domain: 'fyp' | string
currentWorkflow: string
currentStage: string
status: 'idle' | 'running' | 'awaiting_user' | 'blocked' | 'complete'
progress?: { label: string; completed: number; total: number }
currentComponent?: string
allowedActions: string[]
brainSummary?: WorkspaceBrainSummary
}
CopilotKit/shared state is a runtime projection used for rendering. PostgreSQL Workspace Brain remains authoritative.
# 9. Contextual Component Library

Components receive structured data. They do not need to know which internal skill implementation, model, or agent produced it.
# 10. Human-in-the-Loop Model
## 10.1 Mandatory workflow HITL
- Industry selection
- Branch selection
- Problem selection
- FYP direction approval
- Final scope approval
- Consequential dataset selection
- High-impact backward change
- Final proposal readiness
## 10.2 Agent-requested HITL
Use CopilotKit human-in-the-loop when Grey dynamically needs clarification, such as two equally suitable datasets with different tradeoffs. This should not be confused with mandatory workflow interrupts.
## 10.3 Student-initiated clarification
The student can ask “Why this dataset?” or “Can I do this without AI?” without changing stage. Workflow state changes only when an explicit validated action occurs.
# 11. Action Contract
startProject()
selectIndustry(industryId)
selectBranch(branchId)
selectProblem(problemId)
requestMoreProblems()
approveFYPDirection()
modifyScope(patch)
selectDataset(datasetId)
requestDatasetAlternative()
approveTechnicalPlan()
goBack(targetStage)
askGrey(message)
generateProposal()
Action names should remain stable even if backend implementation evolves from a skill to a specialist agent.
# 12. Event-to-UI Contract
research_started           → ResearchProgressCard
research_progress          → update progress
research_complete          → completion summary
problem_options_ready      → ProblemOpportunityCard[]
human_input_required       → contextual selector/dialog
fyp_direction_ready        → FYPDirectionCard
dataset_options_ready      → DatasetRecommendationCard
architecture_ready         → ArchitectureViewer
feasibility_ready          → FeasibilityCard
supervisor_readiness_ready → SupervisorReadinessCard
proposal_ready             → ProposalWorkspace
brain_updated              → refresh Project Brain summary
change_impact_ready        → confirmation dialog
# 13. FYP MVP Journey
Student: “I need an FYP.”
↓
IndustrySelector
↓
BranchSelector
↓
ResearchProgressCard
↓
ProblemOpportunityCard × 3–5
↓ mandatory selection
Functional Area reveal
↓
FYPDirectionCard
↓ approve / adjust
ScopeBuilder
↓ approve
AINecessityCard
↓
DatasetRecommendationCard
↓ select dataset
TechStackCard
↓
ArchitectureViewer
↓
EvaluationPlanCard
↓
FeasibilityCard
↓
SupervisorReadinessCard
↓
ProposalWorkspace
# 14. Project Brain / Workspace Brain UI
For FYP students, keep the user-facing label “Project Brain.” Internally the backend may use “Workspace Brain.” The panel is hidden/collapsible and presents a human-readable summary rather than raw database fields.
PROJECT BRAIN

Discovery
Industry        Defense
Branch          Navy
Area            Maritime Surveillance
Problem         Vessel anomaly detection

Project
Title           AI-Based Maritime...
Scope           Approved

Technical
AI Task         Anomaly Detection
Dataset         MarineCadastre AIS
Stack           Next.js / FastAPI / PostgreSQL

Validation
Feasibility     High
Supervisor      Ready
# 15. Evidence and Long-Running Activity UX
Evidence should not flood the conversation. Cards show evidence strength and source count; “View Evidence” opens a drawer. Long-running skills show high-level status events such as source collection, validation and completion counts—not hidden reasoning.
Grey is researching Navy-related opportunities
✓ Identifying relevant organizations
✓ Reviewing official initiatives
● Reviewing research and public data
○ Extracting student-sized opportunities

21 sources found • 8 high-quality sources
# 16. Change Impact / Go Back
Changing your selected problem will affect:
• FYP direction
• scope
• dataset
• AI strategy
• architecture
• evaluation
• feasibility
• proposal

Your reusable research evidence will remain.

[Cancel]  [Change Problem]
The impact list is calculated by the backend. The frontend never guesses dependencies.
# 17. Future Expansion: Same Shell, New Domains
If Grey later adds Startup, Research, or broader Student journeys, do not create unrelated frontends. Keep the same Grey App Shell and register domain-specific contextual components and navigation entries only when the domain exists.
frontend/
core/
grey-agent/          # our CopilotKit adapter
chat/
sidebar/
drawers/
shared-components/
domains/
fyp/
components/
actions/
routes/
# future only when implemented:
# startup/
# research/
# student/
## 17.1 Example future startup UI

# 18. Future Multi-Agent Backend: No Frontend Rewrite
The student should continue interacting with “Grey.” Whether the backend internally uses one Grey agent or a supervisor plus Research/Technical/Writing agents is hidden. The frontend responds only to stable actions/events and typed output schemas.
Today:
React → CopilotKit → Grey Agent → Skill

Future:
React → CopilotKit → Grey Supervisor → Specialist Agent(s)

Frontend contract stays the same.
# 19. Visual Direction
- Simple, calm, professional, academic and trustworthy.
- White/light-grey surfaces, dark graphite typography, one restrained accent color.
- Conversation-first, not dashboard-first.
- Rounded cards without a childish appearance.
- Minimal gradients and motion.
- Strong hierarchy: decision > explanation > metadata.
# 20. Frontend Guardrails for Claude / Coding Agents
- Do not make every response a custom generative component; use deterministic UI for core navigation and selectors.
- Do not store approved project truth only in React/CopilotKit state.
- Do not expose LangGraph node names, skill class names, model providers or multi-agent internals in product components.
- Do not import CopilotKit directly throughout the entire component tree; prefer the Grey adapter layer.
- Do not build startup/student UI until those domains exist.
- Do not turn the main experience into a complex dashboard; preserve conversation-first UX.
- Do not expose private chain-of-thought. Show safe workflow/tool activity only.
- Every contextual component must have a clear action and typed backend contract.
# 21. Final Frontend Statement
Grey’s frontend is a stable conversation-first shell that renders workflow decisions and skill outputs through CopilotKit, while remaining independent of the backend’s internal agent topology.
This lets Grey evolve from one FYP agent with skills into a broader student/startup companion or a multi-agent system without rebuilding the student-facing product experience.