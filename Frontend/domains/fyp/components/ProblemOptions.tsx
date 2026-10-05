"use client";

/**
 * ProblemOptions — the student's mandatory problem choice (blueprint §13–15).
 *
 * Shown at the PROBLEM_OPTIONS stage when the backend allows "selectProblem".
 * Lists 3–5 ProblemOpportunityCards from the problem_options_ready event.
 *
 * Choosing is a major decision, so it takes two clicks: "Choose this problem"
 * opens a confirmation, and only "Yes, build my FYP around this" calls the
 * Grey `selectProblem` action.
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { ProblemOption } from "../problems";
import { isSampleData, readProblems } from "../problems";
import { ProblemOpportunityCard } from "./ProblemOpportunityCard";

export function ProblemOptions() {
  const { state, isLoading } = useGreyAgent();
  const { selectProblem } = useGreyActions();
  const [pending, setPending] = useState<ProblemOption | null>(null);

  if (state.currentStage !== "PROBLEM_OPTIONS") return null;
  if (!state.allowedActions.includes(Actions.SELECT_PROBLEM)) return null;

  const problems = readProblems(state.eventData);
  const summary = state.eventData?.summary as { provider?: unknown } | undefined;
  const sample = isSampleData(problems, summary?.provider);
  const branch = state.brainSummary?.branch;

  function confirm() {
    if (!pending) return;
    // Errors are already shown on the page by the Grey adapter.
    selectProblem(pending.id).catch(() => {});
  }

  return (
    <section className="flex flex-col gap-4" aria-label="Problem options">
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <p className="text-xs uppercase tracking-wide text-gray-400">Choose your problem</p>
          {sample && (
            <span className="rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-xs font-medium text-amber-700">
              Sample data
            </span>
          )}
        </div>
        <h2 className="text-lg font-semibold text-gray-900">
          Grey found {problems.length} real problems in <span className="text-accent">{branch}</span>
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Each one is backed by evidence you can check. Pick the one you find most interesting.
        </p>
      </div>

      {pending && (
        <div
          role="dialog"
          aria-modal="false"
          aria-labelledby="confirm-problem-title"
          className="rounded-xl border border-accent bg-blue-50 p-5"
        >
          <h3 id="confirm-problem-title" className="font-semibold text-gray-900">
            Build your FYP around “{pending.title}”?
          </h3>
          <p className="mt-1 text-sm text-gray-600">
            This becomes the problem your project is based on. You can&apos;t change it later in this
            version of Grey.
          </p>
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={confirm}
              disabled={isLoading}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 transition-colors"
            >
              {isLoading ? "Saving…" : "Yes, build my FYP around this"}
            </button>
            <button
              type="button"
              onClick={() => setPending(null)}
              disabled={isLoading}
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {problems.map((problem) => (
          <ProblemOpportunityCard
            key={problem.id}
            problem={problem}
            onChoose={setPending}
            disabled={isLoading}
          />
        ))}
      </div>
    </section>
  );
}
