/**
 * Grey UI Adapter — shared types.
 *
 * These types are the stable contract between the Grey adapter and every
 * product component. Components never import CopilotKit types directly;
 * they use these types only.
 */

// ── Workflow status ────────────────────────────────────────────────────────────

/** What the workflow is currently doing. Drives loading states and button availability. */
export type WorkflowStatus =
  | "idle"           // No project started yet
  | "running"        // Grey is working (e.g. fetching evidence)
  | "awaiting_user"  // Grey has paused — the student must make a choice
  | "blocked"        // Something went wrong and Grey cannot continue
  | "complete";      // The current workflow stage is fully done

// ── Project Brain summary ──────────────────────────────────────────────────────

/**
 * A lightweight read of the most recent Project Brain state.
 * Used by the sidebar panel and progress indicators.
 * The full brain is fetched from the backend when needed.
 */
export type WorkspaceBrainSummary = {
  industry?: string;
  industryStatus?: string;
  branch?: string;
  branchStatus?: string;
  workflowState?: string;
  /** Evidence research (Release 0.2): "running" | "complete" | "failed". */
  researchStatus?: string;
  evidenceCount?: number;
  highQualityEvidenceCount?: number;
  /** Problem opportunities (Release 0.3): "running" | "options_ready" | "failed". */
  problemStatus?: string;
  problemOptionCount?: number;
  selectedProblemId?: string;
  selectedProblemTitle?: string;
  /** From problem to FYP (Release 0.5). */
  functionalArea?: string;
  specificArea?: string;
  /** "running" | "draft" | "approved" | "failed". */
  fypDesignStatus?: string;
  fypDesignId?: string;
  fypTitle?: string;
  fypAdjustmentsLeft?: number;
  /** Project definition and scope (Release 0.6): "running" | "draft" | "approved" | "failed". */
  projectDefinitionStatus?: string;
  projectDefinitionId?: string;
  coreFeatureCount?: number;
};

// ── Grey UI state ──────────────────────────────────────────────────────────────

/**
 * The runtime state that drives what the frontend renders.
 *
 * This is the single source of truth for the UI, updated every time
 * the backend emits a GreyEvent. It tells the frontend:
 *   - which component to show (currentStage + allowedActions)
 *   - whether to show spinners or lock the UI (status)
 *   - what the student has decided so far (brainSummary)
 */
export type GreyUIState = {
  workspaceId: string | null;
  domain: "fyp" | string;
  currentWorkflow: string;
  currentStage: string;
  status: WorkflowStatus;
  /** Progress of a long-running step such as evidence research. */
  progress?: { label: string; completed: number; total: number };
  currentComponent?: string;
  allowedActions: string[];
  brainSummary?: WorkspaceBrainSummary;
  /** The `data` of the latest backend event, e.g. { available_industries: [...] }. */
  eventData?: Record<string, unknown>;
  /** The `type` of the latest backend event, so a component knows whose eventData it is. */
  lastEventType?: string;
};

/** The state Grey starts in before any project has been created. */
export const INITIAL_GREY_STATE: GreyUIState = {
  workspaceId: null,
  domain: "fyp",
  currentWorkflow: "discovery",
  currentStage: "idle",
  status: "idle",
  allowedActions: ["startProject"],
};

// ── Grey event (matches backend GreyEvent envelope) ───────────────────────────

/**
 * The event envelope the backend sends after every state-changing action.
 * The frontend reads this to update GreyUIState.
 */
export type GreyEvent = {
  type: string;
  workspace_id: string;
  domain: string;
  workflow: string;
  stage: string;
  status: WorkflowStatus;
  data: Record<string, unknown>;
  brain_patch: Record<string, unknown>;
  allowed_actions: string[];
};

// ── Action names (mirrors backend AllowedAction enum) ─────────────────────────

export const Actions = {
  START_PROJECT: "startProject",
  SELECT_INDUSTRY: "selectIndustry",
  SELECT_BRANCH: "selectBranch",
  START_RESEARCH: "startResearch",
  EXTRACT_PROBLEMS: "extractProblems",
  SELECT_PROBLEM: "selectProblem",
  DESIGN_FYP: "designFYP",
  APPROVE_FYP_DIRECTION: "approveFYPDirection",
  ADJUST_FYP_DIRECTION: "adjustFYPDirection",
  DEFINE_PROJECT: "defineProject",
  MODIFY_SCOPE: "modifyScope",
  APPROVE_SCOPE: "approveScope",
  ASK_GREY: "askGrey",
  GO_BACK: "goBack",
  GENERATE_PROPOSAL: "generateProposal",
} as const;

export type ActionName = (typeof Actions)[keyof typeof Actions];
