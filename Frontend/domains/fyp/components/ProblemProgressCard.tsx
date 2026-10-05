"use client";

/**
 * ProblemProgressCard — Grey turning the evidence into problem options.
 *
 * Shown at the EVIDENCE_RESEARCH stage once problem events arrive
 * (problem_extraction_started / _progress / _failed). Two looks:
 *
 *   running → live checklist ("Reviewing your evidence", "Identifying real
 *             problems…", …) — every label comes from the backend
 *   failed  → the backend's calm message + one button:
 *               "Try again"        when the backend allows extractProblems
 *               "Research again"   when it allows startResearch (evidence too thin)
 *
 * If the connection drops mid-stream, the page shows the error and this card
 * offers "Try again".
 */

import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import { readSteps, StepChecklist } from "./StepChecklist";

export function ProblemProgressCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { extractProblems, startResearch } = useGreyActions();

  if (state.currentStage !== "EVIDENCE_RESEARCH") return null;
  if (!state.lastEventType?.startsWith("problem_extraction")) return null;

  const data = state.eventData;
  const steps = readSteps(data);
  const isFailed = state.status === "blocked";
  const message = typeof data?.message === "string" ? data.message : null;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  const canRetry = state.allowedActions.includes(Actions.EXTRACT_PROBLEMS) || connectionLost;
  const canResearchAgain = state.allowedActions.includes(Actions.START_RESEARCH);

  // Errors are already shown on the page by the Grey adapter,
  // so here we only stop them from becoming "unhandled" errors.
  const retry = () => extractProblems().catch(() => {});
  const researchAgain = () => startResearch().catch(() => {});

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Finding problems">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Real problems</p>
      <h2 className="text-lg font-semibold text-gray-900">
        {isFailed ? "Problems could not be found" : "Grey is finding real problems in your evidence…"}
      </h2>

      {!isFailed && steps.length > 0 && <StepChecklist steps={steps} label="Problem steps" />}

      {isFailed && message && <p className="mt-3 text-sm text-gray-600">{message}</p>}

      {!isLoading && (canRetry || canResearchAgain) && (
        <button
          type="button"
          onClick={canRetry ? retry : researchAgain}
          className="mt-4 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors"
        >
          {canRetry ? "Try again" : "Research again"}
        </button>
      )}
    </section>
  );
}
