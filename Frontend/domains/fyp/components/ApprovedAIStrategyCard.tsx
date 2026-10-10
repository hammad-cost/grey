"use client";

/**
 * ApprovedAIStrategyCard — the end of Release 0.7.
 *
 * Shown at the AI_STRATEGY_APPROVED stage. Summarises what the student
 * committed to: Grey's verdict and, when AI is used, the AI task and the main
 * approach. The data comes from the ai_strategy_approved event; the title
 * falls back to the Project Brain.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { APPROACH_LABELS, labelOf, NECESSITY_LABELS, readAIStrategy, TASK_LABELS } from "../aiStrategy";

export function ApprovedAIStrategyCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "AI_STRATEGY_APPROVED") return null;

  const view = readAIStrategy(state.eventData);
  const strategy = view?.strategy?.strategy ?? null;
  const necessity = strategy?.necessity ?? state.brainSummary?.aiNecessity ?? null;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your approved AI strategy">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your approved AI strategy</p>
      <h2 className="text-lg font-semibold text-gray-900">{view?.fyp_title ?? state.brainSummary?.fypTitle}</h2>

      {necessity && <p className="mt-3 text-sm font-medium text-gray-800">{labelOf(NECESSITY_LABELS, necessity)}</p>}
      {strategy && view?.uses_ai && (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label="AI strategy summary">
          {strategy.task_type && <li>AI task: {labelOf(TASK_LABELS, strategy.task_type)}</li>}
          {strategy.primary_strategy && (
            <li>Main approach: {labelOf(APPROACH_LABELS, strategy.primary_strategy.approach)}</li>
          )}
          {strategy.fallback_strategy && (
            <li>Fallback: {labelOf(APPROACH_LABELS, strategy.fallback_strategy.approach)}</li>
          )}
        </ul>
      )}

      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey will look for datasets that fit your project (coming in a future
        release).
      </p>
    </section>
  );
}
