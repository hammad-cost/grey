"use client";

/**
 * SupervisorReadinessCard — gets the student ready to meet their supervisor
 * (product blueprint §33–35, Release 0.13).
 *
 *   working  → live checklist from the backend
 *   failed   → the backend's calm message + "Try again" (when prepareSupervisorBrief is allowed)
 *   review   → readiness checks (✓ pass / ! needs attention, with what to do);
 *              the supervisor-ready summary (with "Copy summary"); the likely
 *              questions, each opening to its talking points.
 *              [I'm ready for my supervisor] — asks to confirm first
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import { readSupervisorBrief, summaryAsText } from "../supervisorBrief";
import { readSteps, StepChecklist } from "./StepChecklist";

const BRIEF_EVENTS = [
  "supervisor_brief_started", "supervisor_brief_progress", "supervisor_readiness_ready", "supervisor_brief_failed",
];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function SupervisorReadinessCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { prepareSupervisorBrief, confirmSupervisorReady } = useGreyActions();
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);

  if (state.currentStage === "SUPERVISOR_READY") return null;
  if (!state.lastEventType || !BRIEF_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readSupervisorBrief(data);
  const stored = view?.brief ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Preparing your supervisor brief">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Supervisor readiness</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey is preparing you for your supervisor…</h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Supervisor brief steps" />}
        {connectionLost && (
          <button type="button" onClick={() => prepareSupervisorBrief().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.PREPARE_SUPERVISOR_BRIEF);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Preparing your supervisor brief">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Supervisor readiness</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish your supervisor brief</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => prepareSupervisorBrief().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const brief = stored.brief;
  const canConfirm = state.allowedActions.includes(Actions.CONFIRM_SUPERVISOR_READY);

  const copySummary = () => {
    navigator.clipboard?.writeText(summaryAsText(view.fyp_title, brief)).then(() => setCopied(true), () => {});
  };

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Supervisor brief">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Supervisor readiness</p>
      <h2 className="text-lg font-semibold text-gray-900">
        {view.ready ? "You're ready to meet your supervisor" : `${view.attention_count} thing${view.attention_count === 1 ? "" : "s"} to sort out first`}
      </h2>

      <ul className="mt-3 flex flex-col gap-1.5 text-sm" aria-label="Readiness checks">
        {brief.checks.map((c) => (
          <li key={c.check} data-status={c.status}
              className={c.status === "pass" ? "text-gray-700" : "rounded-lg bg-amber-50 px-2 py-1 text-amber-900"}>
            <span className="mr-2 inline-block w-4" aria-hidden="true">{c.status === "pass" ? "✓" : "!"}</span>
            <span className="font-medium">{c.question}</span> <span className="text-gray-600">{c.detail}</span>
          </li>
        ))}
      </ul>

      <div className="mt-5 flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-900">Supervisor-ready summary</h3>
        <button type="button" onClick={copySummary} className="text-xs text-accent hover:underline">
          {copied ? "Copied" : "Copy summary"}
        </button>
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]" aria-label="Supervisor-ready summary">
        {brief.summary.map((item) => (
          <div key={item.label} className="contents">
            <dt className="font-medium text-gray-700">{item.label}</dt>
            <dd className="text-gray-600">{item.value}</dd>
          </div>
        ))}
      </dl>

      <h3 className="mt-5 text-sm font-medium text-gray-900">Questions your supervisor may ask</h3>
      <div className="mt-2 flex flex-col gap-1.5" aria-label="Likely questions">
        {brief.questions.map((q) => (
          <details key={q.id} className="rounded-lg border border-gray-100 px-3 py-2 text-sm">
            <summary className="cursor-pointer font-medium text-gray-800">{q.question}</summary>
            <ul className="mt-1 list-disc pl-5 text-gray-600">
              {q.talking_points.map((point) => <li key={point}>{point}</li>)}
            </ul>
          </details>
        ))}
      </div>

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-ready-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-ready-title" className="font-semibold text-gray-900">Ready to write your proposal?</h3>
          <p className="mt-1 text-sm text-gray-600">
            {view.ready
              ? "Grey will write your proposal from your approved decisions next."
              : "Some checks still need attention. You can continue, but raise them with your supervisor."}
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => confirmSupervisorReady(stored.id).catch(() => {})}
                    disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, I'm ready"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={isLoading} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        canConfirm && (
          <div className="mt-5">
            <button type="button" onClick={() => setConfirming(true)} disabled={isLoading} className={PRIMARY}>
              I&apos;m ready for my supervisor
            </button>
          </div>
        )
      )}
    </section>
  );
}
