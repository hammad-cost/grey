"use client";

/**
 * GreyAgentProvider
 *
 * Wrap the entire application (or page) with this provider.
 * It manages the GreyUIState and makes it available to all child components
 * through the useGreyUIState and useGreyActions hooks.
 *
 * CopilotKit integration:
 *   CopilotKit is installed and ready. It is enabled when
 *   NEXT_PUBLIC_COPILOTKIT_RUNTIME_URL is set in .env.local.
 *   For Release 0.1 this variable is intentionally left empty —
 *   no AI chat runtime is connected yet. The Grey adapter's public
 *   interface (hooks and state shape) is stable and will not change
 *   when CopilotKit is wired up in a future release.
 */

import { useCallback, useState } from "react";
import { GreyContext } from "./context";
import type { GreyEvent, GreyUIState, WorkspaceBrainSummary } from "./types";
import { INITIAL_GREY_STATE } from "./types";

/**
 * The backend sends brain_patch keys in snake_case (e.g. "industry_status").
 * Convert them to the camelCase WorkspaceBrainSummary fields the UI uses.
 * Only keys present in the patch are returned, so unchanged fields are kept.
 */
function toBrainSummary(patch: Record<string, unknown>): WorkspaceBrainSummary {
  const textKeys = {
    industry: "industry",
    industry_status: "industryStatus",
    branch: "branch",
    branch_status: "branchStatus",
    workflow_state: "workflowState",
    research_status: "researchStatus",
    problem_status: "problemStatus",
    selected_problem_id: "selectedProblemId",
    selected_problem_title: "selectedProblemTitle",
    functional_area: "functionalArea",
    specific_area: "specificArea",
    fyp_design_status: "fypDesignStatus",
    fyp_design_id: "fypDesignId",
    fyp_title: "fypTitle",
    project_definition_status: "projectDefinitionStatus",
    project_definition_id: "projectDefinitionId",
    ai_strategy_status: "aiStrategyStatus",
    ai_strategy_id: "aiStrategyId",
    ai_necessity: "aiNecessity",
  } as const;
  const numberKeys = {
    evidence_count: "evidenceCount",
    high_quality_evidence_count: "highQualityEvidenceCount",
    problem_option_count: "problemOptionCount",
    fyp_adjustments_left: "fypAdjustmentsLeft",
    core_feature_count: "coreFeatureCount",
    ai_rechecks_left: "aiRechecksLeft",
  } as const;

  const summary: WorkspaceBrainSummary = {};
  for (const [backendKey, uiKey] of Object.entries(textKeys)) {
    const value = patch[backendKey];
    if (typeof value === "string") summary[uiKey] = value;
  }
  for (const [backendKey, uiKey] of Object.entries(numberKeys)) {
    const value = patch[backendKey];
    if (typeof value === "number") summary[uiKey] = value;
  }
  return summary;
}

/**
 * Research and problem events carry a checklist summary (label, completed_steps, total_steps).
 * Turn it into GreyUIState.progress. Other events have no progress.
 */
function toProgress(data: Record<string, unknown>): GreyUIState["progress"] {
  const { label, completed_steps, total_steps } = data;
  if (
    typeof label === "string" &&
    typeof completed_steps === "number" &&
    typeof total_steps === "number"
  ) {
    return { label, completed: completed_steps, total: total_steps };
  }
  return undefined;
}

interface GreyAgentProviderProps {
  children: React.ReactNode;
}

export function GreyAgentProvider({ children }: GreyAgentProviderProps) {
  const [state, setState] = useState<GreyUIState>(INITIAL_GREY_STATE);
  const [isLoading, setLoadingState] = useState(false);
  const [error, setErrorState] = useState<string | null>(null);

  /**
   * Apply a GreyEvent from the backend.
   * Updates the GreyUIState so the correct component is shown next.
   */
  const applyEvent = useCallback((event: GreyEvent) => {
    setState((prev) => ({
      ...prev,
      workspaceId: event.workspace_id,
      domain: event.domain,
      currentWorkflow: event.workflow,
      currentStage: event.stage,
      status: event.status,
      allowedActions: event.allowed_actions,
      eventData: event.data,
      lastEventType: event.type,
      progress: toProgress(event.data),
      brainSummary: {
        ...prev.brainSummary,
        // brain_patch contains only the fields that changed — merge them in.
        ...toBrainSummary(event.brain_patch),
      },
    }));
  }, []);

  const setLoading = useCallback((loading: boolean) => {
    setLoadingState(loading);
  }, []);

  const setError = useCallback((err: string | null) => {
    setErrorState(err);
  }, []);

  // ── CopilotKit integration (Release 0.1: disabled until runtime URL is set) ──
  // When NEXT_PUBLIC_COPILOTKIT_RUNTIME_URL is set, wrap children with:
  //   <CopilotKit runtimeUrl={runtimeUrl}>{children}</CopilotKit>
  // This is intentionally left for a future release.
  const runtimeUrl = process.env.NEXT_PUBLIC_COPILOTKIT_RUNTIME_URL;
  void runtimeUrl; // suppress unused-variable warning until CopilotKit is wired

  return (
    <GreyContext.Provider
      value={{ state, applyEvent, setLoading, setError, error, isLoading }}
    >
      {children}
    </GreyContext.Provider>
  );
}
