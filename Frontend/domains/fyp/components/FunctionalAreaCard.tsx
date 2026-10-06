"use client";

/**
 * FunctionalAreaCard — "Your Project Area" (product blueprint §16, Release 0.5).
 *
 * Grey works out where the chosen problem sits; the student is never asked.
 * Shown at AREA_CLASSIFICATION and FYP_DESIGN once the area is known:
 *
 *   Industry → Branch → Functional area → Specific area → Problem
 *
 * The names come from the Project Brain summary (brain_patch); the one-line
 * explanation comes from the latest event when it carries the area.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { readArea, readFYP } from "../fypDesign";

const STAGES = ["AREA_CLASSIFICATION", "FYP_DESIGN"];

export function FunctionalAreaCard() {
  const { state } = useGreyAgent();
  const summary = state.brainSummary;

  if (!STAGES.includes(state.currentStage) || !summary?.functionalArea) return null;

  const area = readArea(state.eventData?.area) ?? readFYP(state.eventData)?.area ?? null;
  const rows: [string, string | undefined][] = [
    ["Industry", summary.industry],
    ["Branch", summary.branch],
    ["Functional area", summary.functionalArea],
    ["Specific area", summary.specificArea],
    ["Problem", summary.selectedProblemTitle],
  ];

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Your project area">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Your project area</p>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        {rows.map(([label, value]) =>
          value ? (
            <div key={label} className="contents">
              <dt className="text-gray-500">{label}</dt>
              <dd className="font-medium text-gray-900">{value}</dd>
            </div>
          ) : null
        )}
      </dl>
      {area?.explanation && <p className="mt-3 text-sm text-gray-600">{area.explanation}</p>}
    </section>
  );
}
