"use client";

/**
 * FYPDirectionCard — Grey turns the chosen problem into an FYP, and the
 * student reviews it (product blueprint §17–18, Release 0.5).
 *
 * Three looks, all driven by backend events:
 *
 *   working  → live checklist ("Finding where your project fits",
 *              "Designing a student-sized FYP", …) — labels come from the backend
 *   failed   → the backend's calm message + "Try again" (when designFYP is allowed)
 *   review   → the proposed FYP: title, what you'll build, who uses it, input,
 *              output, main contribution, and "Why this FYP?" (from stored evidence)
 *              [Approve this FYP]  — asks to confirm first (a major decision)
 *              [Adjust]            — one of four controlled changes + optional
 *                                    short note, while redesigns are left (max 3)
 *
 * The card never saves anything itself; it calls the Grey adapter's actions.
 */

import { useState } from "react";
import { Actions, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { FYPDesign, WhyThisFYP } from "../fypDesign";
import { ADJUSTMENT_OPTIONS, adjustmentLabel, isSampleFYP, MAX_NOTE_LENGTH, readFYP } from "../fypDesign";
import { sourceTypeLabel } from "../problems";
import { TierBadge } from "./ProblemOpportunityCard";
import { readSteps, StepChecklist } from "./StepChecklist";

const FYP_EVENTS = [
  "fyp_design_started", "fyp_design_progress", "area_classified", "fyp_direction_ready", "fyp_design_failed",
];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function FYPDirectionCard() {
  const { state, isLoading, error } = useGreyAgent();
  const { designFYP, approveFYPDirection, adjustFYPDirection } = useGreyActions();
  const [confirming, setConfirming] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [choice, setChoice] = useState<string | null>(null);
  const [note, setNote] = useState("");

  if (state.currentStage === "APPROVED_FYP") return null;
  if (!state.lastEventType || !FYP_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const fyp = readFYP(data);
  const design = fyp?.design ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const isRedesign = data?.kind === "adjustment";
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  // ── Working ────────────────────────────────────────────────────────────────
  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Designing your FYP">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Your FYP</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {isRedesign ? "Grey is redesigning your FYP…" : "Grey is turning your problem into an FYP…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="FYP design steps" />}
        {connectionLost && !isRedesign && (
          <button type="button" onClick={() => designFYP().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Failed first design ────────────────────────────────────────────────────
  if (!design) {
    const canRetry = state.allowedActions.includes(Actions.DESIGN_FYP);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Designing your FYP">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Your FYP</p>
        <h2 className="text-lg font-semibold text-gray-900">Your FYP could not be designed</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => designFYP().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  // ── Review ─────────────────────────────────────────────────────────────────
  const canApprove = state.allowedActions.includes(Actions.APPROVE_FYP_DIRECTION);
  const canAdjust = state.allowedActions.includes(Actions.ADJUST_FYP_DIRECTION) && fyp!.adjustments_left > 0;
  const why = fyp!.why_this_fyp;
  const sample = isSampleFYP(why);
  const changed = adjustmentLabel(design.adjustment);

  function approve() {
    approveFYPDirection(design!.id).catch(() => {});
  }

  function redesign() {
    if (!choice) return;
    adjustFYPDirection(choice, note).catch(() => {});
    setAdjusting(false);
    setChoice(null);
    setNote("");
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Proposed FYP">
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <p className="text-xs uppercase tracking-wide text-gray-400">Proposed FYP</p>
        {design.version > 1 && (
          <span className="rounded bg-gray-50 border border-gray-200 px-1.5 py-0.5 text-xs text-gray-600">
            Version {design.version}{changed && ` · ${changed}`}
          </span>
        )}
        {sample && (
          <span className="rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-xs font-medium text-amber-700">
            Sample data
          </span>
        )}
      </div>
      <h2 className="text-lg font-semibold text-gray-900">{design.title}</h2>
      <p className="mt-1 text-sm text-gray-700">{design.summary}</p>

      <DesignDetails design={design} />

      {message && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{message}</p>
      )}

      {why && <WhyThisFYPSection why={why} />}

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-fyp-title"
             className="mt-4 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-fyp-title" className="font-semibold text-gray-900">Approve “{design.title}”?</h3>
          <p className="mt-1 text-sm text-gray-600">
            This becomes your FYP. Grey&apos;s next stages will build on it, and you can&apos;t change it later in
            this version of Grey.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={approve} disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, approve my FYP"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={isLoading} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {canApprove && (
            <button type="button" onClick={() => { setConfirming(true); setAdjusting(false); }}
                    disabled={isLoading} className={PRIMARY}>
              Approve this FYP
            </button>
          )}
          {canAdjust && (
            <button type="button" onClick={() => setAdjusting((open) => !open)} aria-expanded={adjusting}
                    disabled={isLoading} className={SECONDARY}>
              Adjust
            </button>
          )}
          <span className="text-xs text-gray-500">
            {fyp!.adjustments_left > 0
              ? `${fyp!.adjustments_left} of ${fyp!.max_adjustments} redesigns left`
              : `You've used all ${fyp!.max_adjustments} redesigns`}
          </span>
        </div>
      )}

      {adjusting && canAdjust && !confirming && (
        <form
          className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-4"
          aria-label="Adjust your FYP"
          onSubmit={(event) => { event.preventDefault(); redesign(); }}
        >
          <fieldset>
            <legend className="text-sm font-medium text-gray-900">What should Grey change?</legend>
            <p className="text-xs text-gray-500 mb-2">Grey keeps the same problem and redesigns the project.</p>
            <div className="flex flex-col gap-1.5">
              {ADJUSTMENT_OPTIONS.map((option) => (
                <label key={option.value} className="flex items-center gap-2 text-sm text-gray-700">
                  <input type="radio" name="adjustment" value={option.value}
                         checked={choice === option.value} onChange={() => setChoice(option.value)} />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="mt-3 block text-sm font-medium text-gray-900" htmlFor="adjust-note">
            Optional note
          </label>
          <textarea
            id="adjust-note"
            value={note}
            maxLength={MAX_NOTE_LENGTH}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            placeholder="e.g. My university prefers web apps"
            className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900"
          />
          <p className="text-xs text-gray-400">{note.length}/{MAX_NOTE_LENGTH}</p>
          <button type="submit" disabled={!choice || isLoading} className={`mt-2 ${PRIMARY}`}>
            Redesign my FYP
          </button>
        </form>
      )}
    </section>
  );
}

function DesignDetails({ design }: { design: FYPDesign }) {
  const rows: [string, string][] = [
    ["Who uses it", design.target_user],
    ["Input", design.system_input],
    ["Output", design.system_output],
    ["Main contribution", design.main_contribution],
  ];
  return (
    <dl className="mt-4 flex flex-col gap-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt className="font-medium text-gray-700">{label}</dt>
          <dd className="text-gray-600">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function WhyThisFYPSection({ why }: { why: WhyThisFYP }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-gray-100 pt-3">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="why-this-fyp"
              className="text-sm font-medium text-accent hover:underline">
        {open ? "Hide why this FYP" : "Why this FYP?"}
      </button>
      {open && (
        <div id="why-this-fyp" className="mt-3 flex flex-col gap-2 text-sm">
          <p><span className="font-medium text-gray-700">Where the problem came from: </span>
            <span className="text-gray-600">{why.where_the_problem_came_from}</span></p>
          <p><span className="font-medium text-gray-700">Why it matters: </span>
            <span className="text-gray-600">{why.why_it_matters}</span></p>
          <p><span className="font-medium text-gray-700">What organizations are doing: </span>
            <span className="text-gray-600">{why.what_organizations_are_doing}</span></p>
          {why.organizations.length > 0 && (
            <p><span className="font-medium text-gray-700">Who is working on it: </span>
              <span className="text-gray-600">{why.organizations.join(", ")}</span></p>
          )}
          <p><span className="font-medium text-gray-700">How Grey made it student-sized: </span>
            <span className="text-gray-600">{why.how_grey_made_it_student_sized}</span></p>
          <ul className="mt-1 flex flex-col gap-3" aria-label="Evidence behind this FYP">
            {why.evidence.map((source) => (
              <li key={source.evidence_source_id || source.url}>
                <div className="flex flex-wrap items-center gap-2">
                  <TierBadge tier={source.evidence_tier} />
                  <a href={source.url} target="_blank" rel="noopener noreferrer"
                     className="font-medium text-accent hover:underline">{source.title}</a>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  {sourceTypeLabel(source.source_type, source.evidence_tier)} · {source.organization}
                  {source.published_date && ` · ${source.published_date}`}
                </p>
                <p className="text-gray-600 mt-1">“{source.supporting_point}”</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
