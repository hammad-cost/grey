"use client";

/**
 * ProjectDefinitionCard — Grey defines the approved FYP precisely, and the
 * student shapes its scope (product blueprint §19–21, Release 0.6).
 *
 * Three looks, all driven by backend events:
 *
 *   working  → live checklist ("Writing your problem definition, scope and
 *              solution", …) — labels come from the backend
 *   failed   → the backend's calm message + "Try again" (when defineProject is allowed)
 *   review   → Problem definition, Proposed solution, and the Scope in three
 *              lists (Core / Optional / Out of scope). Each feature can be moved
 *              to another list ("Move to…"), within the core limits.
 *              [Approve scope] — asks to confirm first (a major decision)
 *
 * The card never saves anything itself; it calls the Grey adapter's actions.
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { DefinitionView, ScopeItem, ScopeKind } from "../projectDefinition";
import { canMove, itemsOf, MOVE_LABELS, readDefinition, SCOPE_LISTS } from "../projectDefinition";
import { readSteps, StepChecklist } from "./StepChecklist";

const DEFINITION_EVENTS = [
  "project_definition_started", "project_definition_progress", "project_definition_ready",
  "project_definition_failed", "scope_updated",
];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;
const SMALL = "rounded border border-gray-300 bg-white px-2 py-0.5 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed";

export function ProjectDefinitionCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { defineProject, moveScopeItem, approveScope } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "SCOPE_APPROVED") return null;
  if (!state.lastEventType || !DEFINITION_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readDefinition(data);
  const definition = view?.definition ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  // ── Working ────────────────────────────────────────────────────────────────
  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Defining your project">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Your project definition</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey is defining your project…</h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Project definition steps" />}
        {connectionLost && (
          <button type="button" onClick={() => defineProject().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Failed ─────────────────────────────────────────────────────────────────
  if (!view || !definition) {
    const canRetry = state.allowedActions.includes(Actions.DEFINE_PROJECT);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Defining your project">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Your project definition</p>
        <h2 className="text-lg font-semibold text-gray-900">Your project could not be defined</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => defineProject().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Review ─────────────────────────────────────────────────────────────────
  const canApprove = state.allowedActions.includes(Actions.APPROVE_SCOPE);
  const canModify = state.allowedActions.includes(Actions.MODIFY_SCOPE);
  const moved = state.lastEventType === "scope_updated" && typeof data?.moved === "string" ? data.moved : null;
  const problem = definition.problem_definition;
  const solution = definition.proposed_solution;

  function move(item: ScopeItem, to: ScopeKind) {
    moveScopeItem(item.id, to).catch(() => {});
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Project definition">
      <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Your project definition</p>
      <h2 className="text-lg font-semibold text-gray-900">{view.fyp_title}</h2>

      <h3 className="mt-4 font-medium text-gray-900">Problem definition</h3>
      <Details rows={[
        ["What problem exists?", problem.problem_statement],
        ["Who experiences it?", problem.affected_users],
        ["Why does it matter?", problem.why_it_matters],
        ["What currently exists?", problem.current_solutions],
        ["What gap remains?", problem.gap],
        ["What will you build?", problem.what_will_be_built],
      ]} />

      <h3 className="mt-5 font-medium text-gray-900">Proposed solution</h3>
      <Details rows={[
        ["Purpose", solution.system_purpose],
        ["Who uses it", view.target_user],
        ["Input", view.system_input],
        ["Output", view.system_output],
      ]} />
      <p className="mt-3 text-sm font-medium text-gray-700">Main modules</p>
      <ul className="mt-1 flex flex-col gap-1 text-sm text-gray-600" aria-label="Main modules">
        {solution.modules.map((module) => (
          <li key={module.name}><span className="font-medium text-gray-700">{module.name}</span> — {module.purpose}</li>
        ))}
      </ul>
      <p className="mt-3 text-sm font-medium text-gray-700">How it works</p>
      <ol className="mt-1 list-decimal pl-5 text-sm text-gray-600" aria-label="How it works">
        {solution.workflow_steps.map((step, index) => <li key={index}>{step}</li>)}
      </ol>

      <h3 className="mt-5 font-medium text-gray-900">Scope</h3>
      <p className="text-xs text-gray-500">
        Move features between the lists until the scope feels right. Core needs {view.min_core_features}–
        {view.max_core_features} features.
      </p>
      {moved && (
        <p className="mt-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" role="status">
          Moved “{moved}”.
        </p>
      )}
      <div className="mt-3 flex flex-col gap-4">
        {SCOPE_LISTS.map((list) => (
          <ScopeList
            key={list.kind}
            view={view}
            kind={list.kind}
            label={list.label}
            hint={list.hint}
            editable={canModify && !confirming}
            disabled={isLoading}
            onMove={move}
          />
        ))}
      </div>

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-scope-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-scope-title" className="font-semibold text-gray-900">Approve this scope?</h3>
          <p className="mt-1 text-sm text-gray-600">
            Your core scope becomes what you commit to building. Grey&apos;s next stages will plan around it, and
            you can&apos;t change it later in this version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => approveScope(definition.id).catch(() => {})}
                    disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, approve my scope"}
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
              Approve scope
            </button>
          </div>
        )
      )}
    </section>
  );
}

function Details({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="mt-2 flex flex-col gap-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt className="font-medium text-gray-700">{label}</dt>
          <dd className="text-gray-600">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ScopeList({ view, kind, label, hint, editable, disabled, onMove }: {
  view: DefinitionView;
  kind: ScopeKind;
  label: string;
  hint: string;
  editable: boolean;
  disabled: boolean;
  onMove: (item: ScopeItem, to: ScopeKind) => void;
}) {
  const items = itemsOf(view.definition!.scope, kind);
  const others = SCOPE_LISTS.map((list) => list.kind).filter((other) => other !== kind);
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
      <p className="text-sm font-medium text-gray-900">{label} <span className="text-gray-400">({items.length})</span></p>
      <p className="text-xs text-gray-500">{hint}</p>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-gray-400">Nothing here.</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2" aria-label={label}>
          {items.map((item) => (
            <li key={item.id} className="rounded border border-gray-200 bg-white p-2">
              <p className="text-sm font-medium text-gray-800">{item.title}</p>
              <p className="text-xs text-gray-600">{item.description}</p>
              {editable && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-gray-400">Move to:</span>
                  {others.map((to) => (
                    <button
                      key={to}
                      type="button"
                      className={SMALL}
                      disabled={disabled || !canMove(view, item, to)}
                      onClick={() => onMove(item, to)}
                      aria-label={`Move ${item.title} to ${MOVE_LABELS[to]}`}
                    >
                      {MOVE_LABELS[to]}
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
