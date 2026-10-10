"use client";

/**
 * Grey UI Adapter — public hooks.
 *
 * These are the only things product components should import from grey-agent.
 * Internal context wiring and API calls are hidden here.
 *
 * Usage:
 *   const state = useGreyUIState();          // read current stage, status, etc.
 *   const { startProject } = useGreyActions(); // trigger workflow actions
 */

import { useCallback } from "react";
import { useGreyContext } from "./context";
import { readEventStream } from "./stream";
import type { GreyEvent, GreyUIState } from "./types";
import { Actions } from "./types";

// ── API helper ─────────────────────────────────────────────────────────────────

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

/**
 * Thin fetch wrapper.
 * Throws a descriptive Error when the backend returns a non-2xx status.
 */
async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) throw await errorFromResponse(response);

  return response.json() as Promise<T>;
}

/** Turn a failed response into an Error with the backend's message, if any. */
async function errorFromResponse(response: Response): Promise<Error> {
  const body = await response.json().catch(() => ({}));
  return new Error(
    (body as { detail?: string }).detail ??
      `Request failed: ${response.status} ${response.statusText}`
  );
}

/** Each streamed step ends with exactly one of these events. */
const RESEARCH_END_EVENTS = ["research_completed", "research_failed"];
const PROBLEM_END_EVENTS = ["problem_options_ready", "problem_extraction_failed"];
const FYP_DESIGN_END_EVENTS = ["fyp_direction_ready", "fyp_design_failed"];
const DEFINITION_END_EVENTS = ["project_definition_ready", "project_definition_failed"];
const AI_STRATEGY_END_EVENTS = ["ai_strategy_ready", "ai_strategy_failed"];
const DATASET_END_EVENTS = ["dataset_options_ready", "dataset_search_failed"];

/**
 * POST to a streaming endpoint (with an optional JSON body) and apply every
 * event as it arrives. Returns the final event; throws if the request fails
 * or the stream stops early.
 */
async function runEventStream(
  path: string,
  endEvents: string[],
  applyEvent: (event: GreyEvent) => void,
  what: string,
  body?: unknown
): Promise<GreyEvent> {
  const response = await fetch(
    `${BACKEND_URL}${path}`,
    body === undefined
      ? { method: "POST" }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
  if (!response.ok) throw await errorFromResponse(response);
  if (!response.body) throw new Error(`${what} did not start. Please try again.`);

  const lastEvent = await readEventStream(response.body, applyEvent);
  if (!lastEvent || !endEvents.includes(lastEvent.type)) {
    throw new Error(`The connection to Grey was lost during ${what.toLowerCase()}. Please try again.`);
  }
  return lastEvent;
}

// ── Public hooks ───────────────────────────────────────────────────────────────

/**
 * Read the current Grey UI state.
 * Use this to know which stage the student is on, what actions are allowed,
 * and what to render.
 */
export function useGreyUIState(): GreyUIState {
  return useGreyContext().state;
}

/**
 * Access the full Grey context value.
 * Useful when you need both state and loading/error state.
 */
export function useGreyAgent() {
  const { state, isLoading, error } = useGreyContext();
  return { state, isLoading, error };
}

/**
 * Grey workflow actions.
 *
 * Each function calls the FastAPI backend, receives a GreyEvent,
 * and updates GreyUIState automatically.
 *
 * The caller gets back the raw GreyEvent for cases where the component
 * needs the event data (e.g. the list of available branches).
 */
export function useGreyActions() {
  const { applyEvent, setLoading, setError } = useGreyContext();
  const { state } = useGreyContext();

  /**
   * Wrap an API call with loading/error state management.
   * This keeps each action function clean and consistent.
   */
  const run = useCallback(
    async <T>(fn: () => Promise<T>): Promise<T> => {
      setLoading(true);
      setError(null);
      try {
        return await fn();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Something went wrong.";
        setError(message);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [setLoading, setError]
  );

  /** Create a new FYP project and start the Discovery workflow. */
  const startProject = useCallback(
    () =>
      run(async () => {
        const event = await apiFetch<GreyEvent>("/projects", { method: "POST" });
        applyEvent(event);
        return event;
      }),
    [run, applyEvent]
  );

  /** Save the student's industry choice. */
  const selectIndustry = useCallback(
    (industry: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${state.workspaceId}/industry`,
          { method: "POST", body: JSON.stringify({ industry }) }
        );
        applyEvent(event);
        return event;
      }),
    [run, applyEvent, state.workspaceId]
  );

  /** Save the student's branch choice. */
  const selectBranch = useCallback(
    (branch: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${state.workspaceId}/branch`,
          { method: "POST", body: JSON.stringify({ branch }) }
        );
        applyEvent(event);
        return event;
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Run evidence research for the chosen industry and branch, then — when the
   * backend says so (research_completed allows "extractProblems") — find the
   * problem options straight away, so the student doesn't have to click again.
   *
   * The backend streams progress events; each one is applied as soon as it
   * arrives, so the cards update live. Resolves with the final event
   * (problem_options_ready, or research_failed / problem_extraction_failed).
   */
  const startResearch = useCallback(
    () =>
      run(async () => {
        const workspaceId = state.workspaceId;
        if (!workspaceId) throw new Error("No active project.");

        const researched = await runEventStream(
          `/projects/${workspaceId}/research`, RESEARCH_END_EVENTS, applyEvent, "Research"
        );
        if (!researched.allowed_actions.includes(Actions.EXTRACT_PROBLEMS)) return researched;

        return runEventStream(
          `/projects/${workspaceId}/problems`, PROBLEM_END_EVENTS, applyEvent, "Finding problems"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Find problem options from the evidence already saved (e.g. "Try again"
   * after problem_extraction_failed). Streams progress like startResearch.
   * Resolves with problem_options_ready or problem_extraction_failed.
   */
  const extractProblems = useCallback(
    () =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/problems`, PROBLEM_END_EVENTS, applyEvent, "Finding problems"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Save the student's chosen problem (a mandatory decision), then — when the
   * backend says so (problem_selected allows "designFYP") — turn it into an FYP
   * straight away (Release 0.5). Resolves with the final event
   * (fyp_direction_ready or fyp_design_failed, or problem_selected).
   */
  const selectProblem = useCallback(
    (problemId: string) =>
      run(async () => {
        const workspaceId = state.workspaceId;
        if (!workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${workspaceId}/problem`,
          { method: "POST", body: JSON.stringify({ problem_id: problemId }) }
        );
        applyEvent(event);
        if (!event.allowed_actions.includes(Actions.DESIGN_FYP)) return event;

        return runEventStream(
          `/projects/${workspaceId}/fyp-design`, FYP_DESIGN_END_EVENTS, applyEvent, "Designing your FYP"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Design the FYP from the chosen problem (e.g. "Try again" after
   * fyp_design_failed). Streams progress; resolves with fyp_direction_ready
   * or fyp_design_failed.
   */
  const designFYP = useCallback(
    () =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/fyp-design`, FYP_DESIGN_END_EVENTS, applyEvent, "Designing your FYP"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Ask Grey for one controlled redesign of the current FYP (up to 3), with
   * an optional short note. Streams progress like designFYP.
   */
  const adjustFYPDirection = useCallback(
    (adjustment: string, note?: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        const trimmed = note?.trim();
        return runEventStream(
          `/projects/${state.workspaceId}/fyp-design/adjust`,
          FYP_DESIGN_END_EVENTS,
          applyEvent,
          "Redesigning your FYP",
          trimmed ? { adjustment, note: trimmed } : { adjustment }
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Approve the current FYP design (a mandatory decision), then — when the
   * backend says so (fyp_direction_approved allows "defineProject") — write the
   * project definition and scope straight away (Release 0.6). Resolves with the
   * final event (project_definition_ready or project_definition_failed, or
   * fyp_direction_approved).
   */
  const approveFYPDirection = useCallback(
    (designId: string) =>
      run(async () => {
        const workspaceId = state.workspaceId;
        if (!workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${workspaceId}/fyp-design/approve`,
          { method: "POST", body: JSON.stringify({ design_id: designId }) }
        );
        applyEvent(event);
        if (!event.allowed_actions.includes(Actions.DEFINE_PROJECT)) return event;

        return runEventStream(
          `/projects/${workspaceId}/project-definition`, DEFINITION_END_EVENTS, applyEvent, "Defining your project"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Write the project definition and scope (e.g. "Try again" after
   * project_definition_failed). Streams progress; resolves with
   * project_definition_ready or project_definition_failed.
   */
  const defineProject = useCallback(
    () =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/project-definition`,
          DEFINITION_END_EVENTS,
          applyEvent,
          "Defining your project"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /** Move one feature to "core", "optional" or "out_of_scope". The backend checks the scope rules. */
  const moveScopeItem = useCallback(
    (itemId: string, to: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${state.workspaceId}/scope/move`,
          { method: "POST", body: JSON.stringify({ item_id: itemId, to }) }
        );
        applyEvent(event);
        return event;
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Approve the project scope (a mandatory decision), then — when the backend
   * says so (scope_approved allows "checkAINeed") — check whether the project
   * needs AI straight away (Release 0.7). Resolves with the final event
   * (ai_strategy_ready or ai_strategy_failed, or scope_approved).
   */
  const approveScope = useCallback(
    (definitionId: string) =>
      run(async () => {
        const workspaceId = state.workspaceId;
        if (!workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${workspaceId}/scope/approve`,
          { method: "POST", body: JSON.stringify({ definition_id: definitionId }) }
        );
        applyEvent(event);
        if (!event.allowed_actions.includes(Actions.CHECK_AI_NEED)) return event;

        return runEventStream(
          `/projects/${workspaceId}/ai-strategy`, AI_STRATEGY_END_EVENTS, applyEvent, "Checking the AI need"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Check whether the project needs AI and plan the AI strategy (e.g. "Try
   * again" after ai_strategy_failed). Streams progress; resolves with
   * ai_strategy_ready or ai_strategy_failed.
   */
  const checkAINeed = useCallback(
    () =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/ai-strategy`, AI_STRATEGY_END_EVENTS, applyEvent, "Checking the AI need"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Ask Grey to check again with a preference: "without_ai" or "existing_model"
   * (up to 2 times). Streams progress like checkAINeed.
   */
  const recheckAIStrategy = useCallback(
    (preference: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/ai-strategy/recheck`,
          AI_STRATEGY_END_EVENTS,
          applyEvent,
          "Checking again",
          { preference }
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Approve the AI strategy (a mandatory decision), then — when the backend
   * says so (ai_strategy_approved allows "findDatasets") — look for datasets
   * straight away (Release 0.8). Resolves with the final event
   * (dataset_options_ready or dataset_search_failed, or ai_strategy_approved).
   */
  const approveAIStrategy = useCallback(
    (strategyId: string) =>
      run(async () => {
        const workspaceId = state.workspaceId;
        if (!workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${workspaceId}/ai-strategy/approve`,
          { method: "POST", body: JSON.stringify({ strategy_id: strategyId }) }
        );
        applyEvent(event);
        if (!event.allowed_actions.includes(Actions.FIND_DATASETS)) return event;

        return runEventStream(
          `/projects/${workspaceId}/datasets`, DATASET_END_EVENTS, applyEvent, "Looking for datasets"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Search for datasets and recommend two (e.g. "Try again" after
   * dataset_search_failed). Streams progress; resolves with
   * dataset_options_ready or dataset_search_failed.
   */
  const findDatasets = useCallback(
    () =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/datasets`, DATASET_END_EVENTS, applyEvent, "Looking for datasets"
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /**
   * Ask Grey to search again with a preference: "other_options" or "own_data"
   * (up to 2 times). Streams progress like findDatasets.
   */
  const requestDatasetAlternative = useCallback(
    (preference: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        return runEventStream(
          `/projects/${state.workspaceId}/datasets/research`,
          DATASET_END_EVENTS,
          applyEvent,
          "Searching again",
          { preference }
        );
      }),
    [run, applyEvent, state.workspaceId]
  );

  /** Select the "primary" or the "alternative" dataset (a mandatory decision). Release 0.8 ends here. */
  const selectDataset = useCallback(
    (planId: string, choice: string) =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        const event = await apiFetch<GreyEvent>(
          `/projects/${state.workspaceId}/datasets/select`,
          { method: "POST", body: JSON.stringify({ plan_id: planId, choice }) }
        );
        applyEvent(event);
        return event;
      }),
    [run, applyEvent, state.workspaceId]
  );

  return {
    startProject,
    selectIndustry,
    selectBranch,
    startResearch,
    extractProblems,
    selectProblem,
    designFYP,
    adjustFYPDirection,
    approveFYPDirection,
    defineProject,
    moveScopeItem,
    approveScope,
    checkAINeed,
    recheckAIStrategy,
    approveAIStrategy,
    findDatasets,
    requestDatasetAlternative,
    selectDataset,
  };
}
