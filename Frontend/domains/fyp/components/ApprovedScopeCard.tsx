"use client";

/**
 * ApprovedScopeCard — the end of Release 0.6.
 *
 * Shown at the SCOPE_APPROVED stage. Summarises what the student committed to:
 * the FYP title, the core features, and how many optional and out-of-scope
 * features there are. The data comes from the scope_approved event; the title
 * falls back to the Project Brain.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { itemsOf, readDefinition } from "../projectDefinition";

export function ApprovedScopeCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "SCOPE_APPROVED") return null;

  const view = readDefinition(state.eventData);
  const scope = view?.definition?.scope ?? [];
  const core = itemsOf(scope, "core");
  const optional = itemsOf(scope, "optional").length;
  const out = itemsOf(scope, "out_of_scope").length;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your approved scope">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your approved scope</p>
      <h2 className="text-lg font-semibold text-gray-900">{view?.fyp_title ?? state.brainSummary?.fypTitle}</h2>

      {core.length > 0 && (
        <>
          <p className="mt-4 text-sm font-medium text-gray-700">You will build</p>
          <ul className="mt-1 list-disc pl-5 text-sm text-gray-600" aria-label="Core scope">
            {core.map((item) => <li key={item.id}>{item.title}</li>)}
          </ul>
          <p className="mt-3 text-sm text-gray-600">
            Plus {optional} optional {optional === 1 ? "feature" : "features"} if time remains, and {out}{" "}
            {out === 1 ? "feature" : "features"} deliberately left out.
          </p>
        </>
      )}

      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey will check whether your project really needs AI (coming in a
        future release).
      </p>
    </section>
  );
}
