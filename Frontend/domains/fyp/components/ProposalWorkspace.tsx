"use client";

/**
 * ProposalWorkspace — the FYP proposal Grey wrote from the Project Brain
 * (product blueprint §36–37, Release 0.14). The frontend blueprint's name for it.
 *
 *   working  → live checklist from the backend
 *   failed   → the backend's calm message + "Try again" (when generateProposal is allowed);
 *              a failed rewrite keeps the proposal below, with the message on top
 *   review   → contents; every section with where it came from ("Built from your approved
 *              decisions" or "Written by Grey from your approved decisions" + its sources);
 *              references linking to the verified evidence; [Rewrite this section] on the
 *              narrative sections while rewrites are left; [Download as Markdown];
 *              [Finalize proposal] — asks to confirm first, then the journey is complete
 */

import { useState } from "react";
import { Actions, proposalDownloadUrl, useGreyActions, useGreyAgent } from "@/core/grey-agent";
import type { ProposalSection } from "../proposal";
import { readProposal } from "../proposal";
import { readSteps, StepChecklist } from "./StepChecklist";

const PROPOSAL_EVENTS = ["proposal_started", "proposal_progress", "proposal_ready", "proposal_failed"];

const BUTTON = "rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY = `${BUTTON} bg-accent text-white hover:bg-accent-hover`;
const SECONDARY = `${BUTTON} border border-gray-300 bg-white text-gray-700 hover:bg-gray-50`;

export function ProposalWorkspace() {
  const { state, isLoading, error } = useGreyAgent();
  const { generateProposal, rewriteProposalSection, finalizeProposal } = useGreyActions();
  const [confirming, setConfirming] = useState(false);

  if (state.currentStage === "COMPLETE") return null;
  if (!state.lastEventType || !PROPOSAL_EVENTS.includes(state.lastEventType)) return null;

  const data = state.eventData;
  const view = readProposal(data);
  const stored = view?.proposal ?? null;
  const message = typeof data?.message === "string" ? data.message : null;
  const rewriting = typeof data?.rewrite === "string";
  const connectionLost = state.status === "running" && !isLoading && error !== null;

  if (state.status === "running") {
    const steps = readSteps(data);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Writing your proposal">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Proposal</p>
        <h2 className="text-lg font-semibold text-gray-900">
          {rewriting ? "Grey is rewriting a section…" : "Grey is writing your proposal…"}
        </h2>
        {steps.length > 0 && <StepChecklist steps={steps} label="Proposal steps" />}
        {connectionLost && !rewriting && (
          <button type="button" onClick={() => generateProposal().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  if (!view || !stored) {
    const canRetry = state.allowedActions.includes(Actions.GENERATE_PROPOSAL);
    return (
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Writing your proposal">
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Proposal</p>
        <h2 className="text-lg font-semibold text-gray-900">Grey couldn&apos;t finish your proposal</h2>
        {message && <p className="mt-3 text-sm text-gray-600">{message}</p>}
        {canRetry && !isLoading && (
          <button type="button" onClick={() => generateProposal().catch(() => {})} className={`mt-4 ${PRIMARY}`}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const proposal = stored.proposal;
  const canFinalize = state.allowedActions.includes(Actions.FINALIZE_PROPOSAL);
  const canRewrite = state.allowedActions.includes(Actions.REWRITE_PROPOSAL_SECTION);
  const failedRewrite = state.lastEventType === "proposal_failed" ? message : null;
  const sections = proposal.sections.filter((s) => s.id !== "project_title");

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm" aria-label="Proposal">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-wide text-gray-400">Your FYP proposal</p>
        {state.workspaceId && (
          <a href={proposalDownloadUrl(state.workspaceId)} download="fyp-proposal.md"
             className="text-sm text-accent hover:underline">
            Download as Markdown
          </a>
        )}
      </div>
      <h2 className="mt-1 text-xl font-semibold text-gray-900">{proposal.title}</h2>
      <p className="mt-1 text-xs text-gray-500">
        Every section shows where it came from. Facts come straight from your approved decisions; references are the
        sources Grey verified.
      </p>

      {failedRewrite && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
          {failedRewrite}
        </p>
      )}

      <nav className="mt-4" aria-label="Contents">
        <ol className="grid list-decimal grid-cols-1 gap-x-6 pl-5 text-sm text-accent sm:grid-cols-2">
          {sections.map((s) => <li key={s.id}><a href={`#proposal-${s.id}`} className="hover:underline">{s.title}</a></li>)}
        </ol>
      </nav>

      {canRewrite && view.rewritable_sections.length > 0 && (
        <p className="mt-3 text-xs text-gray-500">{view.rewrites_left} of {view.max_rewrites} section rewrites left.</p>
      )}

      <div className="mt-4 flex flex-col gap-5">
        {sections.map((section) => (
          <SectionBlock
            key={section.id}
            section={section}
            references={section.id === "references" ? proposal.references : []}
            canRewrite={canRewrite && view.rewritable_sections.includes(section.id) && !confirming}
            disabled={isLoading}
            onRewrite={() => rewriteProposalSection(section.id).catch(() => {})}
          />
        ))}
      </div>

      {confirming ? (
        <div role="dialog" aria-modal="false" aria-labelledby="confirm-proposal-title"
             className="mt-5 rounded-xl border border-accent bg-blue-50 p-4">
          <h3 id="confirm-proposal-title" className="font-semibold text-gray-900">Finalize your proposal?</h3>
          <p className="mt-1 text-sm text-gray-600">
            This completes your FYP journey with Grey. You can still download the proposal afterwards.
          </p>
          <div className="mt-3 flex gap-3">
            <button type="button" onClick={() => finalizeProposal(stored.id).catch(() => {})}
                    disabled={isLoading} className={PRIMARY}>
              {isLoading ? "Saving…" : "Yes, finalize it"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={isLoading} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        canFinalize && (
          <div className="mt-6">
            <button type="button" onClick={() => setConfirming(true)} disabled={isLoading} className={PRIMARY}>
              Finalize proposal
            </button>
          </div>
        )
      )}
    </section>
  );
}

function SectionBlock({
  section, references, canRewrite, disabled, onRewrite,
}: {
  section: ProposalSection;
  references: { number: number; title: string; organization: string; url: string; published: string | null }[];
  canRewrite: boolean;
  disabled: boolean;
  onRewrite: () => void;
}) {
  const List = section.id === "objectives" ? "ol" : "ul";
  return (
    <article id={`proposal-${section.id}`} aria-label={section.title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-gray-900">{section.title}</h3>
        {canRewrite && (
          <button type="button" onClick={onRewrite} disabled={disabled} className="text-xs text-accent hover:underline">
            Rewrite this section
          </button>
        )}
      </div>
      {section.paragraphs.map((p) => <p key={p} className="mt-1 text-sm text-gray-700">{p}</p>)}
      {references.length > 0 ? (
        <ol className="mt-1 flex flex-col gap-1 text-sm text-gray-700" aria-label="References">
          {references.map((r) => (
            <li key={r.number}>
              [{r.number}] <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                {r.title}
              </a>{" "}
              — {r.organization}{r.published ? ` (${r.published})` : ""}
            </li>
          ))}
        </ol>
      ) : (
        section.items.length > 0 && (
          <List className={`mt-1 pl-5 text-sm text-gray-700 ${List === "ol" ? "list-decimal" : "list-disc"}`}>
            {section.items.map((item) => <li key={item}>{item}</li>)}
          </List>
        )
      )}
      <p className="mt-1 text-xs text-gray-400">
        {section.written_by === "model" ? "Written by Grey from" : "Built from"}: {section.sources.join(", ")}
      </p>
    </article>
  );
}
