"use client";

/**
 * ApprovedTechnicalPlanCard — the approved architecture and evaluation plan (Release 0.11).
 * Shown at the TECHNICAL_PLAN_APPROVED stage: the pipeline in one line and the metrics.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { labelOf, METRIC_LABELS, pipelineOrder, readTechnicalPlan } from "../architecture";

export function ApprovedTechnicalPlanCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "TECHNICAL_PLAN_APPROVED") return null;

  const plan = readTechnicalPlan(state.eventData)?.plan?.plan ?? null;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your approved technical plan">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your approved technical plan</p>
      <h2 className="text-lg font-semibold text-gray-900">Architecture and evaluation</h2>
      {plan && (
        <>
          <p className="mt-2 text-sm text-gray-700">{pipelineOrder(plan).map((c) => c.name).join(" → ")}</p>
          {plan.evaluation.metrics.length > 0 && (
            <p className="mt-1 text-sm text-gray-600">
              Measured by: {plan.evaluation.metrics.map((m) => labelOf(METRIC_LABELS, m.metric)).join(", ")}
            </p>
          )}
        </>
      )}
      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey checks whether the project is feasible.
      </p>
    </section>
  );
}
