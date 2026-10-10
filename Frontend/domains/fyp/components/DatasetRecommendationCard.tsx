"use client";

/**
 * DatasetRecommendationCard — Grey recommends the data for the approved
 * project: one primary dataset and one alternative (product blueprint §24–25,
 * Release 0.8).
 *
 * Three looks, all driven by backend events:
 *
 *   working  → live checklist ("Searching dataset sites", …) — labels come from the backend
 *   failed   → the backend's calm message + "Try again" (when findDatasets is allowed).
 *              A failed re-search keeps the review below, with the message on top.
 *   review   → what the data is for, then the two options side by side: name (a
 *              link to the page Grey found), source, fit, why it fits, size, labels,
 *              license, main features, preparation, limitations — or, for data the
 *              student creates or collects, how to get it.
 *              [Use this dataset] on each — asks to confirm first (a major decision)
 *              [Find other options] [I'd rather create or collect my own data]
 *              — only the re-searches the backend allows, with how many are left
 *
 * The card never saves anything itself; it calls the Grey adapter's actions.
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { DatasetChoice, DatasetOption } from "../datasets";
import { FIT_LABELS, isSampleDatasets, KIND_LABELS, labelOf, readDatasets, RESEARCH_OPTIONS } from "../datasets";
import { readSteps, StepChecklist } from "./StepChecklist";

const DATASET_EVENTS = [
  "dataset_search_started", "dataset_search_progress", "dataset_options_ready", "dataset_search_failed",
];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function DatasetRecommendationCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { findDatasets, requestDatasetAlternative, selectDataset } = useGreyActions();
  const [confirming, setConfirming] = useState<DatasetChoice | null>(null);

  if (state.currentStage === "DATASET_SELECTED") return null;
  if (!state.lastEventType || !DATASET_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readDatasets(data);
  const stored = view?.plan ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const researching = data?.research === true;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  // ── Working ────────────────────────────────────────────────────────────────
  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Looking for datasets">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Dataset discovery</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {researching ? "Grey is searching again…" : "Grey is looking for data for your project…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Dataset search steps" />}
        {connectionLost && !researching && (
          <button type="button" onClick={() => findDatasets().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Failed (first search) ──────────────────────────────────────────────────
  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.FIND_DATASETS);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Looking for datasets">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Dataset discovery</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish looking for datasets</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => findDatasets().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Review ─────────────────────────────────────────────────────────────────
  const plan = stored.plan;
  const canSelect = state.allowedActions.includes(Actions.SELECT_DATASET);
  const canResearch =
    state.allowedActions.includes(Actions.REQUEST_DATASET_ALTERNATIVE) && view.available_researches.length > 0;
  const failedResearch = state.lastEventType === "dataset_search_failed" ? message : null;
  const sample = isSampleDatasets(plan);
  const chosen = confirming ? plan[confirming] : null;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Dataset recommendation">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-wide text-gray-400">Data for your project</p>
        {sample && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">Sample data</span>
        )}
      </div>
      <h2 className="mt-1 text-lg font-semibold text-gray-900">Pick the data you&apos;ll build on</h2>
      <p className="mt-1 text-sm text-gray-600">{plan.purpose}</p>
      {view.pages_found > 0 && (
        <p className="mt-1 text-xs text-gray-400">
          Grey looked at {view.pages_found} dataset pages from {view.searches_used} searches and chose these two.
        </p>
      )}

      {failedResearch && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
          {failedResearch}
        </p>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {(["primary", "alternative"] as const).map((choice) => (
          <DatasetPanel
            key={choice}
            option={plan[choice]}
            heading={choice === "primary" ? "Grey's main pick" : "Alternative"}
            canSelect={canSelect && !confirming}
            disabled={isLoading}
            onSelect={() => setConfirming(choice)}
          />
        ))}
      </div>

      {confirming && chosen ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-dataset-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-dataset-title" className="font-semibold text-gray-900">Use “{chosen.name}”?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Grey&apos;s next stages (technology, architecture, evaluation) will plan around this data, and you
            can&apos;t change it later in this version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => selectDataset(stored.id, confirming).catch(() => {})}
                    disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, use this dataset"}
            </button>
            <button type="button" onClick={() => setConfirming(null)} disabled={isLoading} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        canResearch && (
          <div className="mt-5">
            <p className="text-sm font-medium text-gray-700">Not quite right? Ask Grey to search again</p>
            <p className="text-xs text-gray-500">{view.researches_left} of {view.max_researches} new searches left.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {view.available_researches.map((preference) => (
                <button
                  key={preference}
                  type="button"
                  className={SECONDARY}
                  disabled={isLoading}
                  title={RESEARCH_OPTIONS[preference].hint}
                  onClick={() => requestDatasetAlternative(preference).catch(() => {})}
                >
                  {RESEARCH_OPTIONS[preference].label}
                </button>
              ))}
            </div>
          </div>
        )
      )}
    </section>
  );
}

/** One recommended dataset with everything the student needs to judge it. */
function DatasetPanel({
  option, heading, canSelect, disabled, onSelect,
}: {
  option: DatasetOption;
  heading: string;
  canSelect: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <article className="flex flex-col rounded-lg border border-gray-200 p-4" aria-label={heading}>
      <p className="text-xs font-medium uppercase tracking-wide text-accent">{heading}</p>
      <h3 className="mt-1 font-semibold text-gray-900">
        {option.url ? (
          <a href={option.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
            {option.name}
          </a>
        ) : (
          option.name
        )}
      </h3>
      <p className="mt-0.5 text-xs text-gray-500">
        {labelOf(KIND_LABELS, option.kind)}
        {option.source && option.url ? ` · ${option.source}` : ""}
        {option.fit ? ` · ${labelOf(FIT_LABELS, option.fit)}` : ""}
      </p>
      <p className="mt-2 text-sm text-gray-600">{option.relevance}</p>

      <dl className="mt-3 flex flex-col gap-1.5 text-sm">
        {option.how_to_get && <Detail term="How to get it" value={option.how_to_get} />}
        <Detail term="Size" value={option.size} />
        <Detail term="Labels" value={option.labels} />
        <Detail term="License" value={option.license} />
        {option.main_features.length > 0 && <Detail term="Main features" value={option.main_features.join(", ")} />}
      </dl>

      {option.preprocessing.length > 0 && (
        <>
          <p className="mt-3 text-sm font-medium text-gray-700">Preparation needed</p>
          <ul className="mt-1 list-disc pl-5 text-sm text-gray-600" aria-label={`${heading}: preparation needed`}>
            {option.preprocessing.map((step) => <li key={step}>{step}</li>)}
          </ul>
        </>
      )}
      {option.limitations.length > 0 && (
        <>
          <p className="mt-3 text-sm font-medium text-gray-700">Limitations</p>
          <ul className="mt-1 list-disc pl-5 text-sm text-gray-600" aria-label={`${heading}: limitations`}>
            {option.limitations.map((limit) => <li key={limit}>{limit}</li>)}
          </ul>
        </>
      )}

      {canSelect && (
        <button type="button" onClick={onSelect} disabled={disabled} className={`mt-4 self-start ${PRIMARY}`}>
          Use this dataset
        </button>
      )}
    </article>
  );
}

function Detail({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt className="inline font-medium text-gray-700">{term}: </dt>
      <dd className="inline text-gray-600">{value}</dd>
    </div>
  );
}
