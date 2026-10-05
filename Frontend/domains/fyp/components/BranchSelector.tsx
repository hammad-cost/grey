"use client";

/**
 * BranchSelector — the second student decision in the FYP journey.
 *
 * Shows a short message from Grey and one clickable card per branch of the
 * industry the student already chose. Clicking a card calls the Grey
 * `selectBranch` action, which saves the choice to the Project Brain and
 * moves the workflow to EVIDENCE_RESEARCH.
 *
 * Contract with the Grey adapter (same as IndustrySelector):
 *   - The branch list comes from the latest backend event
 *     (eventData.available_branches) — it is never hardcoded here.
 *   - The component only renders when the backend says "selectBranch"
 *     is an allowed action.
 *   - Cards are disabled while Grey is busy, so a choice can't be sent twice.
 */

import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";

/** Read the branch list from the event data, ignoring anything that isn't text. */
function readBranches(eventData?: Record<string, unknown>): string[] {
  const value = eventData?.available_branches;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function BranchSelector() {
  const { state, isLoading } = useGreyAgent();
  const { selectBranch } = useGreyActions();

  if (!state.allowedActions.includes(Actions.SELECT_BRANCH)) return null;

  const branches = readBranches(state.eventData);
  const industry = state.brainSummary?.industry;

  function handleSelect(branch: string) {
    // Errors are already shown on the page by the Grey adapter,
    // so here we only stop them from becoming "unhandled" errors.
    selectBranch(branch).catch(() => {});
  }

  return (
    <section className="flex flex-col gap-4">
      {/* Grey's message */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">
          Step 2 of 2
        </p>
        <h2 className="text-lg font-semibold text-gray-900">
          Which branch of <span className="text-accent">{industry}</span> do you
          want to focus on?
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          A narrower focus helps Grey find real, evidence-backed problems for your FYP.
        </p>
      </div>

      {/* Branch cards */}
      <ul className="grid grid-cols-2 sm:grid-cols-3 gap-3" aria-label="Branches">
        {branches.map((branch) => (
          <li key={branch}>
            <button
              type="button"
              onClick={() => handleSelect(branch)}
              disabled={isLoading}
              className="w-full rounded-lg border border-gray-200 bg-white px-4 py-3 text-left text-sm font-medium text-gray-800 hover:border-accent hover:text-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {branch}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
