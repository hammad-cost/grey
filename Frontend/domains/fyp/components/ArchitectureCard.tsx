"use client";

/**
 * ArchitectureCard — Grey's system architecture and evaluation plan
 * (product blueprint §30–31, Release 0.11).
 *
 *   working  → live checklist from the backend
 *   failed   → the backend's calm message + "Try again" (when designArchitecture is allowed);
 *              a failed redesign keeps the review below, with the message on top
 *   review   → the summary; the architecture as a top-to-bottom pipeline of boxes
 *              (kind, name, role, technology) and how data moves between them; the
 *              evaluation plan: metrics with why and goal, system tests, baseline.
 *              [Make it simpler] — while redesigns are left
 *              [Approve technical plan] — asks to confirm first
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { TechnicalPlan } from "../architecture";
import {
  COMPONENT_KIND_LABELS,
  labelOf,
  METRIC_LABELS,
  pipelineOrder,
  readTechnicalPlan,
  TEST_LABELS,
} from "../architecture";
import { readSteps, StepChecklist } from "./StepChecklist";

const ARCHITECTURE_EVENTS = ["architecture_started", "architecture_progress", "architecture_ready", "architecture_failed"];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function ArchitectureCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { designArchitecture, redesignArchitecture, approveTechnicalPlan } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "TECHNICAL_PLAN_APPROVED") return null;
  if (!state.lastEventType || !ARCHITECTURE_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readTechnicalPlan(data);
  const stored = view?.plan ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const redesigning = data?.redesign === true;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Designing the architecture">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Architecture and evaluation</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {redesigning ? "Grey is simplifying the architecture…" : "Grey is designing your architecture…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Architecture steps" />}
        {connectionLost && !redesigning && (
          <button type="button" onClick={() => designArchitecture().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.DESIGN_ARCHITECTURE);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Designing the architecture">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Architecture and evaluation</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish the architecture</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => designArchitecture().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const plan = stored.plan;
  const canApprove = state.allowedActions.includes(Actions.APPROVE_TECHNICAL_PLAN);
  const canRedesign = state.allowedActions.includes(Actions.REDESIGN_ARCHITECTURE) && view.can_redesign;
  const failedRedesign = state.lastEventType === "architecture_failed" ? message : null;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Technical plan">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Architecture and evaluation</p>
      <h2 className="text-lg font-semibold text-gray-900">Your system architecture</h2>
      <p className="mt-1 text-sm text-gray-600">{plan.summary}</p>

      {failedRedesign && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
          {failedRedesign}
        </p>
      )}

      <ArchitectureDiagram plan={plan} />
      <EvaluationSection plan={plan} />

      {canRedesign && !confirming && (
        <div className="mt-5">
          <p className="text-xs text-gray-500">{view.redesigns_left} of {view.max_redesigns} redesigns left.</p>
          <button type="button" className={`mt-2 ${SECONDARY}`} disabled={isLoading}
                  onClick={() => redesignArchitecture("simpler").catch(() => {})}>
            Make it simpler
          </button>
        </div>
      )}

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-architecture-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-architecture-title" className="font-semibold text-gray-900">
            Approve this architecture and evaluation plan?
          </h3>
          <p className="mt-1 text-sm text-gray-600">
            Grey&apos;s feasibility check and your proposal will use it, and you can&apos;t change it later in this
            version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => approveTechnicalPlan(stored.id).catch(() => {})}
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
              Approve technical plan
            </button>
          </div>
        )
      )}
    </section>
  );
}

/** The architecture as a top-to-bottom pipeline, then how the data moves. */
export function ArchitectureDiagram({ plan }: { plan: TechnicalPlan }) {
  const byId = new Map(plan.architecture.components.map((c) => [c.id, c.name]));
  return (
    <>
      <h3 className="mt-4 text-sm font-medium text-gray-900">Architecture</h3>
      <ol className="mt-2 flex flex-col items-stretch gap-1" aria-label="Architecture diagram">
        {pipelineOrder(plan).map((component, index) => (
          <li key={component.id} className="flex flex-col items-center">
            {index > 0 && <span className="text-gray-400" aria-hidden="true">↓</span>}
            <div className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
              <p className="font-medium text-gray-900">
                <span className="mr-2 rounded bg-white px-1.5 py-0.5 text-xs text-gray-500">
                  {labelOf(COMPONENT_KIND_LABELS, component.kind)}
                </span>
                {component.name}
                {component.technology && <span className="ml-2 text-xs text-accent">{component.technology}</span>}
              </p>
              <p className="text-gray-600">{component.role}</p>
            </div>
          </li>
        ))}
      </ol>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-gray-600">How data moves ({plan.architecture.flows.length})</summary>
        <ul className="mt-1 list-disc pl-5 text-gray-600" aria-label="Data flows">
          {plan.architecture.flows.map((flow) => (
            <li key={`${flow.source}-${flow.target}-${flow.data}`}>
              {byId.get(flow.source) ?? flow.source} → {byId.get(flow.target) ?? flow.target}: {flow.data}
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}

function EvaluationSection({ plan }: { plan: TechnicalPlan }) {
  const { metrics, tests, baseline } = plan.evaluation;
  return (
    <>
      <h3 className="mt-4 text-sm font-medium text-gray-900">How you will prove it works</h3>
      {metrics.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5 text-sm" aria-label="Evaluation metrics">
          {metrics.map((m) => (
            <li key={m.metric} className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="font-medium text-gray-800">{labelOf(METRIC_LABELS, m.metric)} — <span className="font-normal">{m.goal}</span></p>
              <p className="text-gray-600">{m.why}</p>
            </li>
          ))}
        </ul>
      )}
      <ul className="mt-2 list-disc pl-5 text-sm text-gray-600" aria-label="System tests">
        {tests.map((t) => <li key={t.kind}><span className="font-medium">{labelOf(TEST_LABELS, t.kind)}:</span> {t.how}</li>)}
      </ul>
      {baseline && <p className="mt-2 text-sm text-gray-600"><span className="font-medium">Baseline:</span> {baseline}</p>}
    </>
  );
}
