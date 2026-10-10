"use client";

/**
 * SelectedDatasetCard — the end of Release 0.8.
 *
 * Shown at the DATASET_SELECTED stage. Summarises the data the student
 * committed to: its name (a link for a public dataset), where it comes from,
 * and its license. The data comes from the dataset_selected event; the name
 * falls back to the Project Brain.
 */

import { useGreyAgent } from "@/core/grey-agent";
import { KIND_LABELS, labelOf, readDatasets, selectedOption } from "../datasets";

export function SelectedDatasetCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "DATASET_SELECTED") return null;

  const view = readDatasets(state.eventData);
  const option = selectedOption(view?.plan ?? null);
  const name = option?.name ?? state.brainSummary?.datasetSelected;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your selected dataset">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your selected dataset</p>
      <h2 className="text-lg font-semibold text-gray-900">
        {option?.url ? (
          <a href={option.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{name}</a>
        ) : (
          name
        )}
      </h2>

      {option && (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label="Dataset summary">
          <li>{labelOf(KIND_LABELS, option.kind)}{option.url && option.source ? ` from ${option.source}` : ""}</li>
          {option.how_to_get && <li>{option.how_to_get}</li>}
          <li>License: {option.license}</li>
        </ul>
      )}

      <p className="mt-4 text-sm text-gray-400">
        Saved to your Project Brain. Next, Grey will check pretrained models and APIs for your project (coming in a
        future release).
      </p>
    </section>
  );
}
