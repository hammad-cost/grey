"use client";

/**
 * IndustrySelector — the first student decision in the FYP journey.
 *
 * Shows a short message from Grey and one clickable card per industry.
 * Clicking a card calls the Grey `selectIndustry` action, which saves the
 * choice to the Project Brain and moves the workflow to BRANCH_SELECTION.
 *
 * Contract with the Grey adapter:
 *   - The industry list comes from the latest backend event
 *     (eventData.available_industries) — it is never hardcoded here.
 *   - The component only renders when the backend says "selectIndustry"
 *     is an allowed action.
 *   - Cards are disabled while Grey is busy, so a choice can't be sent twice.
 */

import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";

/** Read the industry list from the event data, ignoring anything that isn't text. */
function readIndustries(eventData?: Record<string, unknown>): string[] {
  const value = eventData?.available_industries;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function IndustrySelector() {
  const { state, isLoading } = useGreyAgent();
  const { selectIndustry } = useGreyActions();

  if (!state.allowedActions.includes(Actions.SELECT_INDUSTRY)) return null;

  const industries = readIndustries(state.eventData);

  function handleSelect(industry: string) {
    // Errors are already shown on the page by the Grey adapter,
    // so here we only stop them from becoming "unhandled" errors.
    selectIndustry(industry).catch(() => {});
  }

  return (
    <section className="flex flex-col gap-4">
      {/* Grey's message */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">
          Step 1 of 2
        </p>
        <h2 className="text-lg font-semibold text-gray-900">
          Which industry do you want to build your FYP for?
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Pick the area you care about most. Next, you&apos;ll narrow it down to a
          specific branch.
        </p>
      </div>

      {/* Industry cards */}
      <ul className="grid grid-cols-2 sm:grid-cols-3 gap-3" aria-label="Industries">
        {industries.map((industry) => (
          <li key={industry}>
            <button
              type="button"
              onClick={() => handleSelect(industry)}
              disabled={isLoading}
              className="w-full rounded-lg border border-gray-200 bg-white px-4 py-3 text-left text-sm font-medium text-gray-800 hover:border-accent hover:text-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {industry}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
