"use client";

/**
 * ResearchProgressCard — Grey researching evidence for the chosen branch.
 *
 * Shown at the EVIDENCE_RESEARCH stage. It has five looks:
 *
 *   ready    → "Grey is ready to research" + Start research button
 *   running  → live checklist + source counts (updated by each streamed event)
 *   complete → summary of the evidence saved to the Project Brain
 *   failed   → a calm message + Try again button
 *   compact  → once Grey moves on to finding problems (problem_* events),
 *              a one-line research summary; ProblemProgressCard takes over
 *
 * Contract with the Grey adapter (same as the selectors):
 *   - Everything shown comes from the latest backend event (eventData) and
 *     brainSummary — the research plan is never hardcoded here.
 *   - The Start / Try again button only appears when the backend allows
 *     "startResearch", or when the connection dropped mid-research.
 */

import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import { readSteps, StepChecklist } from "./StepChecklist";

type ResearchSummary = {
  total_sources: number;
  high_quality_count: number;
  by_tier: Record<string, number>;
  by_category?: Record<string, number>;
  startups_confirmed?: number;
};

/** "3 startups confirmed · 2 news articles · …" — only the kinds that were found. */
function foundByType(summary: ResearchSummary): string {
  const count = (key: string) => summary.by_category?.[key] ?? 0;
  const parts: [number, string, string][] = [
    [summary.startups_confirmed ?? 0, "startup confirmed", "startups confirmed"],
    [count("news"), "news article", "news articles"],
    [count("official_sources"), "government source", "government sources"],
    [count("research"), "research paper", "research papers"],
    [count("datasets"), "dataset", "datasets"],
  ];
  return parts
    .filter(([n]) => n > 0)
    .map(([n, one, many]) => `${n} ${n === 1 ? one : many}`)
    .join(" · ");
}

function readNumber(eventData: Record<string, unknown> | undefined, key: string): number {
  const value = eventData?.[key];
  return typeof value === "number" ? value : 0;
}

function readSummary(eventData?: Record<string, unknown>): ResearchSummary | null {
  const value = eventData?.summary as ResearchSummary | undefined;
  return value && typeof value.total_sources === "number" ? value : null;
}

export function ResearchProgressCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { startResearch } = useGreyActions();

  if (state.currentStage !== "EVIDENCE_RESEARCH") return null;

  const industry = state.brainSummary?.industry;
  const branch = state.brainSummary?.branch;

  // Grey has moved on to finding problems: show a short research summary only.
  if (state.lastEventType?.startsWith("problem_")) {
    return (
      <section
        className="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm"
        aria-label="Evidence research"
      >
        <p className="text-sm text-gray-700">
          <span className="text-green-600" aria-hidden="true">✓ </span>
          Research complete — Grey saved{" "}
          <strong>{state.brainSummary?.evidenceCount ?? 0} sources</strong> about{" "}
          <strong>{branch}</strong>, including {state.brainSummary?.highQualityEvidenceCount ?? 0}{" "}
          high-quality (Tier A).
        </p>
      </section>
    );
  }

  const data = state.eventData;
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
          Grey will discover startups working in this branch and confirm them on their
          own websites, then check industry news, government sources, research papers
          and public datasets — and save the evidence to your Project Brain.
        </p>
      )}

      {/* Running / complete: the checklist */}
      {steps.length > 0 && !isFailed && <StepChecklist steps={steps} label="Research steps" />}

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
          {foundByType(summary) && <p className="mt-1">{foundByType(summary)}</p>}
          <p className="mt-1 text-gray-500">
            Tier A: {summary.by_tier.A ?? 0} · Tier B: {summary.by_tier.B ?? 0} · Tier C:{" "}
            {summary.by_tier.C ?? 0}
          </p>
          <p className="mt-2 text-gray-400">
            Next, Grey turns this evidence into real problem options for you to choose from.
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
