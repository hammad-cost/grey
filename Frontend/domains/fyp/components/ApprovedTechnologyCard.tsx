"use client";

/**
 * ApprovedTechnologyCard — the approved technology plan (Release 0.10).
 * Shown at the TECHNOLOGY_APPROVED stage: one line per stack decision.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { AREA_LABELS, labelOf, readTechnology } from "../technology";

export function ApprovedTechnologyCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "TECHNOLOGY_APPROVED") return null;

  const plan = readTechnology(state.eventData)?.plan?.plan ?? null;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your approved technology plan">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your approved technology plan</p>
      <h2 className="text-lg font-semibold text-gray-900">Technology and hardware</h2>
      {plan && (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label="Technology summary">
          {plan.stack.map((choice) => (
            <li key={choice.area}>{labelOf(AREA_LABELS, choice.area)}: {choice.choice}</li>
          ))}
          {plan.hardware.filter((item) => item.essential).map((item) => (
            <li key={`${item.kind}-${item.name}`}>Hardware: {item.name}</li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey designs your system architecture and evaluation plan.
      </p>
    </section>
  );
}
