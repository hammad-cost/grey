"use client";

/**
 * ApprovedModelsCard — the approved model plan (Release 0.9).
 * Shown at the MODELS_APPROVED stage: Grey's advice and what to do with each option.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { labelOf, MODEL_USE_LABELS, readModels } from "../models";

export function ApprovedModelsCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "MODELS_APPROVED") return null;

  const plan = readModels(state.eventData)?.plan?.plan ?? null;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your approved model plan">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your approved model plan</p>
      <h2 className="text-lg font-semibold text-gray-900">
        {plan && !plan.needs_model ? "No model needed" : "Models and APIs"}
      </h2>
      {plan && <p className="mt-2 text-sm text-gray-700">{plan.summary}</p>}
      {plan && plan.options.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label="Model plan summary">
          {plan.options.map((option) => (
            <li key={option.url ?? option.name}>{option.name}: {labelOf(MODEL_USE_LABELS, option.use)}</li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey plans your technology stack and hardware.
      </p>
    </section>
  );
}
