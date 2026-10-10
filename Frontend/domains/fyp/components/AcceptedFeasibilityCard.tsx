"use client";

/**
 * AcceptedFeasibilityCard — the accepted feasibility report (Release 0.12).
 * Shown at the FEASIBILITY_ACCEPTED stage: the overall rating and the main risks.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { OVERALL_LABELS, readFeasibility } from "../feasibility";

export function AcceptedFeasibilityCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "FEASIBILITY_ACCEPTED") return null;

  const report = readFeasibility(state.eventData)?.report?.report ?? null;
  const overall = report?.overall ?? state.brainSummary?.feasibilityOverall;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your feasibility report">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your feasibility report</p>
      <h2 className="text-lg font-semibold text-gray-900">
        Overall feasibility: {overall ? OVERALL_LABELS[overall] ?? overall : "—"}
      </h2>
      {report && (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label="Main risks summary">
          {report.main_risks.map((r) => <li key={r.risk}>{r.risk}</li>)}
        </ul>
      )}
      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey checks whether you&apos;re ready to meet your supervisor.
      </p>
    </section>
  );
}
