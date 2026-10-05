"use client";

/**
 * ResearchProgressCard — Grey researching evidence for the chosen branch.
 *
 * Shown at the EVIDENCE_RESEARCH stage. It has four looks:
 *
 *   ready    → "Grey is ready to research" + Start research button
 *   running  → live checklist + source counts (updated by each streamed event)
 *   complete → summary of the evidence saved to the Project Brain
 *   failed   → a calm message + Try again button
 *
 * Contract with the Grey adapter (same as the selectors):
 *   - Everything shown comes from the latest backend event (eventData) and
 *     brainSummary — the research plan is never hardcoded here.
 *   - The Start / Try again button only appears when the backend allows
 *     "startResearch", or when the connection dropped mid-research.
 */

import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";

type StepState = "done" | "active" | "pending";
type ResearchStep = { id: string; label: string; state: StepState };
type ResearchSummary = {
  total_sources: number;
  high_quality_count: number;
  by_tier: Record<string, number>;
};

/** Read the checklist from the event data, ignoring anything malformed. */
function readSteps(eventData?: Record<string, unknown>): ResearchStep[] {
  const value = eventData?.steps;
  if (!Array.isArray(value)) return [];
  return value.filter(
    (step): step is ResearchStep =>
      typeof step?.id === "string" &&
      typeof step?.label === "string" &&
      ["done", "active", "pending"].includes(step?.state)
  );
}

function readNumber(eventData: Record<string, unknown> | undefined, key: string): number {
  const value = eventData?.[key];
  return typeof value === "number" ? value : 0;
}

function readSummary(eventData?: Record<string, unknown>): ResearchSummary | null {
  const value = eventData?.summary as ResearchSummary | undefined;
  return value && typeof value.total_sources === "number" ? value : null;
}

const STEP_ICON: Record<StepState, string> = { done: "✓", active: "●", pending: "○" };
const STEP_STYLE: Record<StepState, string> = {
  done: "text-green-600",
  active: "text-accent font-medium",
  pending: "text-gray-400",
};

export function ResearchProgressCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { startResearch } = useGreyActions();

  if (state.currentStage !== "EVIDENCE_RESEARCH") return null;

  const data = state.eventData;
  const industry = state.brainSummary?.industry;
  const branch = state.brainSummary?.branch;
  const steps = readSteps(data);
  const summary = readSummary(data);
  const sourcesFound = readNumber(data, "sources_found");
  const highQuality = readNumber(data, "high_quality_sources");

  const isComplete = state.status === "complete" && summary !== null;
  const isFailed = state.status === "blocked";
  const isRunning = state.status === "running" && isLoading;
  const canStart =
    state.allowedActions.includes(Actions.START_RESEARCH) ||
    // The stream stopped before research ended (the page shows the error).
    (state.status === "running" && !isLoading && error !== null);

  function handleStart() {
    // Errors are already shown on the page by the Grey adapter,
    // so here we only stop them from becoming "unhandled" errors.
    startResearch().catch(() => {});
  }

  return (
    <section
      className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
      aria-label="Evidence research"
    >
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Evidence research</p>
      <h2 className="text-lg font-semibold text-gray-900">
        {isComplete
          ? "Research complete"
          : isFailed
            ? "Research could not be completed"
            : steps.length > 0
              ? "Grey is researching real problems…"
              : "Grey is ready to research evidence"}
      </h2>
      <p className="mt-1 text-sm text-gray-500">
        <strong>{industry}</strong> · <strong>{branch}</strong>
      </p>

      {/* Ready: explain what will happen */}
      {steps.length === 0 && !isFailed && (
        <p className="mt-3 text-sm text-gray-600">
          Grey will look for organizations, official sources, research and public
          datasets about real problems in this branch, then save the evidence to
          your Project Brain.
        </p>
      )}

      {/* Running / complete: the checklist */}
      {steps.length > 0 && !isFailed && (
        <ul className="mt-4 flex flex-col gap-1.5 text-sm" aria-label="Research steps">
          {steps.map((step) => (
            <li key={step.id} className={STEP_STYLE[step.state]} data-state={step.state}>
              <span className="inline-block w-5" aria-hidden="true">
                {STEP_ICON[step.state]}
              </span>
              {step.label}
            </li>
          ))}
        </ul>
      )}

      {/* Source counts while running */}
      {steps.length > 0 && !isComplete && !isFailed && (
        <p className="mt-3 text-sm text-gray-500">
          {sourcesFound} sources found • {highQuality} high-quality sources
        </p>
      )}

      {/* Complete: what was saved */}
      {isComplete && summary && (
        <div className="mt-4 rounded-lg bg-green-50 border border-green-200 px-4 py-3 text-sm text-gray-700">
          <p>
            Grey saved <strong>{summary.total_sources} sources</strong> to your Project
            Brain, including <strong>{summary.high_quality_count} high-quality</strong>{" "}
            (Tier A) sources.
          </p>
          <p className="mt-1 text-gray-500">
            Tier A: {summary.by_tier.A ?? 0} · Tier B: {summary.by_tier.B ?? 0} · Tier C:{" "}
            {summary.by_tier.C ?? 0}
          </p>
          <p className="mt-2 text-gray-400">
            Next, Grey will turn this evidence into problem options (coming in a future release).
          </p>
        </div>
      )}

      {/* Failed: the backend's safe message */}
      {isFailed && typeof data?.message === "string" && (
        <p className="mt-3 text-sm text-gray-600">{data.message}</p>
      )}

      {canStart && !isRunning && (
        <button
          type="button"
          onClick={handleStart}
          disabled={isLoading}
          className="mt-4 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 transition-colors"
        >
          {steps.length > 0 || isFailed || error ? "Try again" : "Start research"}
        </button>
      )}
    </section>
  );
}
