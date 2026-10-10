"use client";

/**
 * TechnologyPlanCard — Grey's focused technology stack and the hardware the
 * project needs (product blueprint §27–29, Release 0.10).
 *
 *   working  → live checklist from the backend
 *   failed   → the backend's calm message + "Try again" (when planTechnology is allowed);
 *              a failed re-plan keeps the review below, with the message on top
 *   review   → the summary; one decision per area with why it fits; hardware with
 *              purpose, essential / nice to have, cost and a cheaper alternative.
 *              [Make it simpler / cheaper] — while re-plans are left
 *              [Approve technology plan] — asks to confirm first
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import { AREA_LABELS, COST_LABELS, labelOf, readTechnology } from "../technology";
import { readSteps, StepChecklist } from "./StepChecklist";

const TECHNOLOGY_EVENTS = [
  "technology_plan_started", "technology_plan_progress", "technology_plan_ready", "technology_plan_failed",
];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function TechnologyPlanCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { planTechnology, replanTechnology, approveTechnology } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "TECHNOLOGY_APPROVED") return null;
  if (!state.lastEventType || !TECHNOLOGY_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readTechnology(data);
  const stored = view?.plan ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const replanning = data?.replan === true;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Planning the technology">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Technology and hardware</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {replanning ? "Grey is making the plan simpler…" : "Grey is planning your technology…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Technology plan steps" />}
        {connectionLost && !replanning && (
          <button type="button" onClick={() => planTechnology().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.PLAN_TECHNOLOGY);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Planning the technology">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Technology and hardware</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish the technology plan</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => planTechnology().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const plan = stored.plan;
  const canApprove = state.allowedActions.includes(Actions.APPROVE_TECHNOLOGY);
  const canReplan = state.allowedActions.includes(Actions.REPLAN_TECHNOLOGY) && view.can_replan;
  const failedReplan = state.lastEventType === "technology_plan_failed" ? message : null;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Technology plan">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Technology and hardware</p>
      <h2 className="text-lg font-semibold text-gray-900">Your technology plan</h2>
      <p className="mt-1 text-sm text-gray-600">{plan.summary}</p>

      {failedReplan && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
          {failedReplan}
        </p>
      )}

      <h3 className="mt-4 text-sm font-medium text-gray-900">Technology stack</h3>
      <dl className="mt-2 flex flex-col gap-2 text-sm" aria-label="Technology stack">
        {plan.stack.map((choice) => (
          <div key={choice.area} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
            <dt className="font-medium text-gray-800">
              {labelOf(AREA_LABELS, choice.area)}: <span className="text-accent">{choice.choice}</span>
            </dt>
            <dd className="text-gray-600">{choice.reason}</dd>
          </div>
        ))}
      </dl>

      <h3 className="mt-4 text-sm font-medium text-gray-900">Hardware</h3>
      <ul className="mt-2 flex flex-col gap-2 text-sm" aria-label="Hardware">
        {plan.hardware.map((item) => (
          <li key={`${item.kind}-${item.name}`} className="rounded-lg border border-gray-100 px-3 py-2">
            <p className="font-medium text-gray-800">
              {item.name}
              <span className="ml-2 text-xs font-normal text-gray-500">
                {item.essential ? "Essential" : "Nice to have"} · {labelOf(COST_LABELS, item.cost)}
              </span>
            </p>
            <p className="text-gray-600">{item.purpose}</p>
            {item.alternative && <p className="text-xs text-gray-500">Alternative: {item.alternative}</p>}
          </li>
        ))}
      </ul>

      {canReplan && !confirming && (
        <div className="mt-5">
          <p className="text-xs text-gray-500">{view.replans_left} of {view.max_replans} re-plans left.</p>
          <button type="button" className={`mt-2 ${SECONDARY}`} disabled={isLoading}
                  onClick={() => replanTechnology("simpler").catch(() => {})}>
            Make it simpler / cheaper
          </button>
        </div>
      )}

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-technology-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-technology-title" className="font-semibold text-gray-900">Approve this technology plan?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Grey&apos;s architecture and evaluation plan will build on it, and you can&apos;t change it later in this
            version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => approveTechnology(stored.id).catch(() => {})}
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
              Approve technology plan
            </button>
          </div>
        )
      )}
    </section>
  );
}
