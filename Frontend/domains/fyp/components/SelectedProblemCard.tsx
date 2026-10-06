"use client";

/**
 * SelectedProblemCard — the end of discovery (Release 0.3).
 *
 * Shown at the PROBLEM_SELECTED stage. Summarises what the student has decided:
 * industry, branch and the chosen problem, with the evidence behind it.
 * The problem comes from the problem_selected event.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { readProblem } from "../problems";

export function SelectedProblemCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "PROBLEM_SELECTED") return null;

  const problem = readProblem(state.eventData?.problem);
  const title = problem?.title ?? state.brainSummary?.selectedProblemTitle;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your FYP problem">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your FYP problem</p>
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      <p className="mt-1 text-sm text-gray-600">
        Industry: <strong>{state.brainSummary?.industry}</strong>
        {" · "}
        Branch: <strong>{state.brainSummary?.branch}</strong>
      </p>

      {problem && (
        <dl className="mt-4 flex flex-col gap-2 text-sm">
          <div>
            <dt className="font-medium text-gray-700">Real-world problem</dt>
            <dd className="text-gray-600">{problem.real_world_problem}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Possible FYP direction</dt>
            <dd className="text-gray-600">{problem.possible_fyp_direction}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Evidence</dt>
            <dd className="text-gray-600">
              Backed by {problem.evidence.length} {problem.evidence.length === 1 ? "source" : "sources"} saved in
              your Project Brain.
            </dd>
          </div>
        </dl>
      )}

      <p className="mt-4 text-sm text-gray-400">
        Next, Grey turns this problem into a concrete FYP for you to review.
      </p>
    </section>
  );
}
