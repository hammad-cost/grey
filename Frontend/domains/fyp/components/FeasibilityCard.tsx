"use client";

/**
 * FeasibilityCard — is the approved FYP realistic? (product blueprint §32, Release 0.12)
 *
 *   working  → live checklist from the backend
 *   failed   → the backend's calm message + "Try again" (when assessFeasibility is allowed)
 *   review   → the overall High / Medium / Low (computed by the backend) and how it was
 *              reached; the 13 dimensions with level, finding and reason (marked "from
 *              your decisions" or "Grey's judgement"); the main risks with mitigations.
 *              A Low result shows a clear warning.
 *              [Accept and continue] — asks to confirm first
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import { dimensionName, LEVEL_LABELS, OVERALL_LABELS, readFeasibility } from "../feasibility";
import { readSteps, StepChecklist } from "./StepChecklist";

const FEASIBILITY_EVENTS = ["feasibility_started", "feasibility_progress", "feasibility_ready", "feasibility_failed"];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

const OVERALL_STYLE: Record<string, string> = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
};
const LEVEL_STYLE: Record<string, string> = {
  favourable: "text-green-700",
  moderate: "text-amber-700",
  concern: "text-red-700",
};

export function FeasibilityCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { assessFeasibility, acceptFeasibility } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "FEASIBILITY_ACCEPTED") return null;
  if (!state.lastEventType || !FEASIBILITY_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readFeasibility(data);
  const stored = view?.report ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Checking feasibility">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Feasibility</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey is checking whether your project is feasible…</h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Feasibility steps" />}
        {connectionLost && (
          <button type="button" onClick={() => assessFeasibility().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.ASSESS_FEASIBILITY);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Checking feasibility">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Feasibility</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish the feasibility check</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => assessFeasibility().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const report = stored.report;
  const canAccept = state.allowedActions.includes(Actions.ACCEPT_FEASIBILITY);

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Feasibility report">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Feasibility</p>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-900">Overall feasibility</h2>
        <span className={`rounded-full px-3 py-0.5 text-sm font-semibold ${OVERALL_STYLE[report.overall] ?? ""}`}
              aria-label="Overall feasibility rating">
          {OVERALL_LABELS[report.overall] ?? report.overall}
        </span>
      </div>
      <p className="mt-1 text-sm text-gray-600">{report.summary}</p>
      <p className="mt-1 text-xs text-gray-500">{report.overall_reason}</p>

      {report.overall === "low" && (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
          Grey rates this project as hard to finish. Talk to your supervisor about the concerns below before you
          commit to it.
        </p>
      )}

      <ul className="mt-4 flex flex-col gap-1.5 text-sm" aria-label="Feasibility dimensions">
        {report.dimensions.map((d) => (
          <li key={d.dimension} className="rounded-lg border border-gray-100 px-3 py-2">
            <p className="font-medium text-gray-800">
              {dimensionName(view, d.dimension)}:{" "}
              <span className={LEVEL_STYLE[d.level] ?? ""}>{d.finding}</span>
              <span className="ml-2 text-xs font-normal text-gray-400">
                {LEVEL_LABELS[d.level] ?? d.level} · {d.assessed_by === "facts" ? "from your decisions" : "Grey's judgement"}
              </span>
            </p>
            <p className="text-gray-600">{d.reason}</p>
          </li>
        ))}
      </ul>

      <h3 className="mt-4 text-sm font-medium text-gray-900">Main risks</h3>
      <ul className="mt-1 list-disc pl-5 text-sm text-gray-600" aria-label="Main risks">
        {report.main_risks.map((r) => (
          <li key={r.risk}><span className="font-medium">{r.risk}</span> — {r.mitigation}</li>
        ))}
      </ul>

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-feasibility-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-feasibility-title" className="font-semibold text-gray-900">Accept this feasibility report?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Grey&apos;s supervisor readiness check and your proposal will include it.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => acceptFeasibility(stored.id).catch(() => {})}
                    disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, accept it"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={isLoading} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        canAccept && (
          <div className="mt-5">
            <button type="button" onClick={() => setConfirming(true)} disabled={isLoading} className={PRIMARY}>
              Accept and continue
            </button>
          </div>
        )
      )}
    </section>
  );
}
