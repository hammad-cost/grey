"use client";

/**
 * ModelRecommendationCard — Grey checks whether pretrained models, APIs or
 * code already exist for the AI task, and what to do with each (product
 * blueprint §26, Release 0.9).
 *
 *   working  → live checklist from the backend
 *   failed   → the backend's calm message + "Try again" (when findModels is allowed);
 *              a failed re-search keeps the review below, with the message on top
 *   review   → Grey's overall advice, then 0–3 options: name (a link to the page
 *              Grey found), kind · source, what to do with it and why, which part
 *              of the system it serves, limitations. A project without AI simply
 *              shows "no model needed".
 *              [Look for other models] — only when the backend allows it, with how many are left
 *              [Approve model plan] — asks to confirm first
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { ModelOption } from "../models";
import {
  isSampleModels,
  labelOf,
  MODEL_KIND_LABELS,
  MODEL_RESEARCH_OPTIONS,
  MODEL_USE_LABELS,
  readModels,
} from "../models";
import { readSteps, StepChecklist } from "./StepChecklist";

const MODEL_EVENTS = ["model_search_started", "model_search_progress", "models_ready", "model_search_failed"];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

const USE_STYLE: Record<string, string> = {
  use_directly: "bg-green-100 text-green-800",
  fine_tune: "bg-blue-100 text-blue-800",
  benchmark: "bg-gray-100 text-gray-800",
  avoid: "bg-red-100 text-red-800",
};

export function ModelRecommendationCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { findModels, requestOtherModels, approveModels } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "MODELS_APPROVED") return null;
  if (!state.lastEventType || !MODEL_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readModels(data);
  const stored = view?.plan ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const researching = data?.research === true;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Looking for models">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Pretrained models and APIs</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {researching ? "Grey is searching again…" : "Grey is checking what already exists…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Model search steps" />}
        {connectionLost && !researching && (
          <button type="button" onClick={() => findModels().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.FIND_MODELS);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Looking for models">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Pretrained models and APIs</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish looking for models</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => findModels().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const plan = stored.plan;
  const canApprove = state.allowedActions.includes(Actions.APPROVE_MODELS);
  const canResearch =
    state.allowedActions.includes(Actions.REQUEST_OTHER_MODELS) && view.available_researches.length > 0;
  const failedResearch = state.lastEventType === "model_search_failed" ? message : null;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Model plan">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-wide text-gray-400">Pretrained models and APIs</p>
        {isSampleModels(plan) && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">Sample data</span>
        )}
      </div>
      <h2 className="mt-1 text-lg font-semibold text-gray-900">
        {plan.needs_model ? "What already exists for your project" : "No model needed"}
      </h2>
      <p className="mt-1 text-sm text-gray-600">{plan.summary}</p>
      {view.pages_found > 0 && (
        <p className="mt-1 text-xs text-gray-400">
          Grey looked at {view.pages_found} pages from {view.searches_used} searches.
        </p>
      )}

      {failedResearch && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
          {failedResearch}
        </p>
      )}

      {plan.needs_model && plan.options.length === 0 && (
        <p className="mt-3 text-sm text-gray-600">
          Nothing ready-made fits well, so you build the AI part as your approved AI strategy plans.
        </p>
      )}
      {plan.options.length > 0 && (
        <div className="mt-4 flex flex-col gap-3">
          {plan.options.map((option) => <ModelPanel key={option.url ?? option.name} option={option} />)}
        </div>
      )}

      {canResearch && !confirming && (
        <div className="mt-5">
          <p className="text-xs text-gray-500">{view.researches_left} of {view.max_researches} new searches left.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {view.available_researches.map((preference) => (
              <button
                key={preference}
                type="button"
                className={SECONDARY}
                disabled={isLoading}
                title={MODEL_RESEARCH_OPTIONS[preference].hint}
                onClick={() => requestOtherModels(preference).catch(() => {})}
              >
                {MODEL_RESEARCH_OPTIONS[preference].label}
              </button>
            ))}
          </div>
        </div>
      )}

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-models-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-models-title" className="font-semibold text-gray-900">Approve this model plan?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Grey&apos;s technology plan will build on it, and you can&apos;t change it later in this version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => approveModels(stored.id).catch(() => {})}
                    disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, approve it"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={isLoading} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        canApprove && (
          <div className="mt-5">
            <button type="button" onClick={() => setConfirming(true)} disabled={isLoading} className={PRIMARY}>
              Approve model plan
            </button>
          </div>
        )
      )}
    </section>
  );
}

function ModelPanel({ option }: { option: ModelOption }) {
  return (
    <article className="rounded-lg border border-gray-200 p-4" aria-label={option.name}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-gray-900">
          {option.url ? (
            <a href={option.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{option.name}</a>
          ) : (
            option.name
          )}
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${USE_STYLE[option.use] ?? "bg-gray-100 text-gray-800"}`}>
          {labelOf(MODEL_USE_LABELS, option.use)}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-gray-500">
        {labelOf(MODEL_KIND_LABELS, option.kind)}{option.source ? ` · ${option.source}` : ""}
        {option.role ? ` · for ${option.role}` : ""}
      </p>
      <p className="mt-2 text-sm text-gray-600">{option.reason}</p>
      {option.limitations.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label={`${option.name}: limitations`}>
          {option.limitations.map((limit) => <li key={limit}>{limit}</li>)}
        </ul>
      )}
    </article>
  );
}
