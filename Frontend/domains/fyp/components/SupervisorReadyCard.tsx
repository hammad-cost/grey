"use client";

/**
 * SupervisorReadyCard — the student confirmed they're ready (Release 0.13).
 * Shown at the SUPERVISOR_READY stage.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { readSupervisorBrief } from "../supervisorBrief";

export function SupervisorReadyCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "SUPERVISOR_READY") return null;

  const view = readSupervisorBrief(state.eventData);
  const attention = view?.attention_count ?? state.brainSummary?.supervisorAttentionCount ?? 0;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Ready for your supervisor">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Ready for your supervisor</p>
      <h2 className="text-lg font-semibold text-gray-900">{view?.fyp_title ?? state.brainSummary?.fypTitle}</h2>
      <p className="mt-2 text-sm text-gray-600">
        {attention === 0
          ? "Every readiness check passed."
          : `${attention} readiness check${attention === 1 ? "" : "s"} to raise with your supervisor.`}
      </p>
      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey writes your proposal from your approved decisions.
      </p>
    </section>
  );
}
