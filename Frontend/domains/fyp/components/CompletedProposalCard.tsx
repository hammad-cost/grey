"use client";

/**
 * CompletedProposalCard — the end of the FYP journey (Release 0.14).
 * Shown at the COMPLETE stage: the finalized proposal and a download link.
 */

import { proposalDownloadUrl, useGreyAgent } from "@/core/grey-agent";
import { readProposal } from "../proposal";

export function CompletedProposalCard() {
  const { state } = useGreyAgent();

  if (state.currentStage !== "COMPLETE") return null;

  const view = readProposal(state.eventData);
  const title = view?.proposal?.proposal.title ?? view?.fyp_title ?? state.brainSummary?.fypTitle;

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-6" aria-label="Your finalized proposal">
      <p className="text-xs uppercase tracking-wide text-green-600 mb-1">Your FYP journey is complete</p>
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      <p className="mt-2 text-sm text-gray-600">
        Your proposal is finalized and saved to your Project Brain. Every section traces back to a decision you
        approved, and every reference is a source Grey verified.
      </p>
      {state.workspaceId && (
        <a href={proposalDownloadUrl(state.workspaceId)} download="fyp-proposal.md"
           className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover">
          Download your proposal
        </a>
      )}
    </section>
  );
}
