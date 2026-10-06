"use client";

/**
 * ApprovedFYPCard — the end of Release 0.5.
 *
 * Shown at the APPROVED_FYP stage. Summarises the approved FYP: where it sits
 * (industry → branch → functional area → specific area), what the student
 * will build, and how many saved sources back it. The data comes from the
 * fyp_direction_approved event; the summary falls back to the Project Brain.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { readFYP } from "../fypDesign";

export function ApprovedFYPCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "APPROVED_FYP") return null;

  const fyp = readFYP(state.eventData);
  const design = fyp?.design;
  const summary = state.brainSummary;
  const path = [summary?.industry, summary?.branch, summary?.functionalArea, summary?.specificArea].filter(Boolean);
  const sources = fyp?.why_this_fyp?.evidence.length ?? 0;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your approved FYP">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your approved FYP</p>
      <h2 className="text-lg font-semibold text-gray-900">{design?.title ?? summary?.fypTitle}</h2>
      {path.length > 0 && <p className="mt-1 text-sm text-gray-600">{path.join(" → ")}</p>}

      {design && (
        <dl className="mt-4 flex flex-col gap-2 text-sm">
          <div>
            <dt className="font-medium text-gray-700">What you&apos;ll build</dt>
            <dd className="text-gray-600">{design.summary}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Who uses it</dt>
            <dd className="text-gray-600">{design.target_user}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Main contribution</dt>
            <dd className="text-gray-600">{design.main_contribution}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Problem</dt>
            <dd className="text-gray-600">
              {fyp?.problem_title ?? summary?.selectedProblemTitle}
              {sources > 0 && ` — backed by ${sources} ${sources === 1 ? "source" : "sources"} saved in your Project Brain.`}
            </dd>
          </div>
        </dl>
      )}

      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey will define your project&apos;s scope (coming in a future release).
      </p>
    </section>
  );
}
