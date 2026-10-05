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

/** Research ends with exactly one of these events. */
const RESEARCH_END_EVENTS = ["research_completed", "research_failed"];

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
   * Run evidence research for the chosen industry and branch.
   *
   * The backend streams progress events while it researches; each one is
   * applied as soon as it arrives, so the progress card updates live.
   * Resolves with the final event (research_completed or research_failed).
   */
  const startResearch = useCallback(
    () =>
      run(async () => {
        if (!state.workspaceId) throw new Error("No active project.");
        const response = await fetch(
          `${BACKEND_URL}/projects/${state.workspaceId}/research`,
          { method: "POST" }
        );
        if (!response.ok) throw await errorFromResponse(response);
        if (!response.body) throw new Error("Research did not start. Please try again.");

        const lastEvent = await readEventStream(response.body, applyEvent);
        if (!lastEvent || !RESEARCH_END_EVENTS.includes(lastEvent.type)) {
          throw new Error("The connection to Grey was lost during research. Please try again.");
        }
        return lastEvent;
      }),
    [run, applyEvent, state.workspaceId]
  );

  return { startProject, selectIndustry, selectBranch, startResearch };
}
