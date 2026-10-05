# Grey Development Rules

Grey is an AI companion platform. The first product domain is the FYP Companion for final-year students.

## Source Documents

Read the specifications in `/docs`.

Authority order:

1. Grey V1 Product Blueprint defines the product behavior and student journey.
2. Grey Backend Skills-First Blueprint v2 defines backend architecture.
3. Grey Frontend CopilotKit Skills-First Blueprint v2 defines frontend architecture and frontend/backend interaction.

## Core Architecture

Frontend:
- Next.js
- React
- TypeScript
- CopilotKit

Backend:
- Python
- FastAPI
- LangGraph

Persistence:
- PostgreSQL / Supabase

## Core Concepts

Workflow = controls the student journey and state transitions.

Skill = reusable intelligent ability Grey knows how to perform.

Tool = low-level operation or external service used by skills.

Project Brain = persistent accepted truth about the student's FYP.

Project Brain must remain the source of truth, not chat history or CopilotKit state.

## Backend Rules

- LangGraph orchestrates workflows.
- Skills must contain reusable intelligent logic.
- Tools must be provider-independent where practical.
- FastAPI routes must stay thin.
- Keep business logic out of API routes.
- Do not put large prompts directly inside LangGraph nodes.
- Use typed schemas for inputs and outputs.
- Use deterministic application logic where AI is unnecessary.
- MVP uses one Grey agent with skills.
- Architecture should allow a skill to become a specialist agent later without rewriting the product.

## Frontend Rules

- UI should be conversation-first and simple.
- Do not build a large dashboard as the main interface.
- Structured UI appears contextually when Grey needs user input or presents results.
- CopilotKit handles agent-facing interaction, HITL, shared runtime state, frontend actions, streaming and contextual UI.
- CopilotKit state is not persistent project truth.
- Major student decisions should use structured UI such as cards, buttons, dialogs or approvals.

## Development Rules

- Build Grey incrementally using vertical slices.
- Do not build the entire product in one shot.
- Before implementing a feature, inspect existing code.
- Reuse existing abstractions.
- Modify the minimum necessary files.
- Do not refactor unrelated code.
- Do not introduce unnecessary dependencies.
- Keep the code understandable for a beginner.
- Add tests for each implemented slice.
- Run tests/type checking before considering a slice complete.
- Never hardcode secrets.
- Use `.env` and `.env.example`.
- Do not implement future startup, multi-agent, student-companion or other domain features until explicitly requested.

## Current Build Goal

Start with Release 0.1 only:

1. Create/start an FYP project.
2. Student chooses an industry.
3. Save the industry to Project Brain.
4. Show relevant branches.
5. Student chooses a branch.
6. Save the branch to Project Brain.
7. LangGraph transitions the project to EVIDENCE_RESEARCH.
8. Stop there.

Do not implement actual evidence research yet.
Do not make real LLM calls yet.
