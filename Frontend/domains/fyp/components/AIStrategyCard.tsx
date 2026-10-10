"use client";

/**
 * AIStrategyCard — Grey checks whether the approved project really needs AI
 * and, if it does, how the AI part should be built (product blueprint §22–23,
 * Release 0.7).
 *
 * Three looks, all driven by backend events:
 *
 *   working  → live checklist ("Checking whether your project really needs
 *              AI", …) — labels come from the backend
 *   failed   → the backend's calm message + "Try again" (when checkAINeed is allowed).
 *              A failed re-check keeps the review below, with the message on top.
 *   review   → Grey's verdict and why, how it would work without AI, and — when
 *              AI is used — the AI part, task, primary approach and fallback.
 *              [Can I do this without AI?] [Use a ready-made model instead]
 *              — only the re-checks the backend allows, with how many are left
 *              [Approve AI strategy] — asks to confirm first (a major decision)
 *
 * The card never saves anything itself; it calls the Grey adapter's actions.
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { AIStrategy } from "../aiStrategy";
import {
  APPROACH_LABELS,
  labelOf,
  NECESSITY_LABELS,
  readAIStrategy,
  RECHECK_OPTIONS,
  TASK_LABELS,
} from "../aiStrategy";
import { readSteps, StepChecklist } from "./StepChecklist";

const AI_STRATEGY_EVENTS = [
  "ai_strategy_started", "ai_strategy_progress", "ai_strategy_ready", "ai_strategy_failed",
];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function AIStrategyCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { checkAINeed, recheckAIStrategy, approveAIStrategy } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "AI_STRATEGY_APPROVED") return null;
  if (!state.lastEventType || !AI_STRATEGY_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readAIStrategy(data);
  const stored = view?.strategy ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const rechecking = data?.recheck === true;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  // ── Working ────────────────────────────────────────────────────────────────
  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Checking the AI need">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">AI necessity check</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {rechecking ? "Grey is checking again…" : "Grey is checking whether your project needs AI…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="AI check steps" />}
        {connectionLost && !rechecking && (
          <button type="button" onClick={() => checkAINeed().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Failed (first check) ───────────────────────────────────────────────────
  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.CHECK_AI_NEED);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Checking the AI need">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">AI necessity check</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t check whether your project needs AI</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => checkAINeed().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Review ─────────────────────────────────────────────────────────────────
  const strategy = stored.strategy;
  const canApprove = state.allowedActions.includes(Actions.APPROVE_AI_STRATEGY);
  const canRecheck = state.allowedActions.includes(Actions.RECHECK_AI_STRATEGY) && view.available_rechecks.length > 0;
  const failedRecheck = state.lastEventType === "ai_strategy_failed" ? message : null;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="AI strategy">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Does your project need AI?</p>
      <h2 className="text-lg font-semibold text-gray-900">{labelOf(NECESSITY_LABELS, strategy.necessity)}</h2>
      <p className="mt-1 text-sm text-gray-600">{strategy.necessity_reason}</p>

      {failedRecheck && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
          {failedRecheck}
        </p>
      )}

      <dl className="mt-4 flex flex-col gap-2 text-sm">
        <div>
          <dt className="font-medium text-gray-700">Without AI</dt>
          <dd className="text-gray-600">{strategy.without_ai}</dd>
        </div>
      </dl>

      {view.uses_ai && <AIPlan strategy={strategy} />}

      <p className="mt-4 text-sm font-medium text-gray-700">Parts that need no AI</p>
      <ul className="mt-1 list-disc pl-5 text-sm text-gray-600" aria-label="Parts that need no AI">
        {strategy.non_ai_components.map((part) => <li key={part}>{part}</li>)}
      </ul>

      {canRecheck && !confirming && (
        <div className="mt-5">
          <p className="text-sm font-medium text-gray-700">Not sure? Ask Grey to check again</p>
          <p className="text-xs text-gray-500">
            {view.rechecks_left} of {view.max_rechecks} re-checks left. Grey keeps its answer if your preference
            doesn&apos;t fit the project, and tells you why.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {view.available_rechecks.map((preference) => (
              <button
                key={preference}
                type="button"
                className={SECONDARY}
                disabled={isLoading}
                title={RECHECK_OPTIONS[preference].hint}
                onClick={() => recheckAIStrategy(preference).catch(() => {})}
              >
                {RECHECK_OPTIONS[preference].label}
              </button>
            ))}
          </div>
        </div>
      )}

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-ai-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-ai-title" className="font-semibold text-gray-900">Approve this AI strategy?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Grey&apos;s next stages (datasets, technology, architecture) will plan around it, and you can&apos;t
            change it later in this version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => approveAIStrategy(stored.id).catch(() => {})}
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
              Approve AI strategy
            </button>
          </div>
        )
      )}
    </section>
  );
}

/** The AI part of the project: what it does, the task, and how it is built. */
function AIPlan({ strategy }: { strategy: AIStrategy }) {
  const primary = strategy.primary_strategy;
  const fallback = strategy.fallback_strategy;
  return (
    <div className="mt-4 rounded-lg border border-gray-100 bg-gray-50 p-3">
      <h3 className="text-sm font-medium text-gray-900">AI / ML strategy</h3>
      <dl className="mt-2 flex flex-col gap-2 text-sm">
        {strategy.ai_component && (
          <div>
            <dt className="font-medium text-gray-700">Where AI is used</dt>
            <dd className="text-gray-600">{strategy.ai_component}</dd>
          </div>
        )}
        {strategy.task_type && (
          <div>
            <dt className="font-medium text-gray-700">AI task</dt>
            <dd className="text-gray-600">{labelOf(TASK_LABELS, strategy.task_type)}</dd>
          </div>
        )}
        {primary && (
          <div>
            <dt className="font-medium text-gray-700">Main approach</dt>
            <dd className="text-gray-600">
              <span className="font-medium">{labelOf(APPROACH_LABELS, primary.approach)}</span> — {primary.reason}
            </dd>
          </div>
        )}
        {fallback && (
          <div>
            <dt className="font-medium text-gray-700">Fallback</dt>
            <dd className="text-gray-600">
              <span className="font-medium">{labelOf(APPROACH_LABELS, fallback.approach)}</span> — {fallback.reason}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}
