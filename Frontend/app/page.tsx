"use client";

/**
 * Home page — FYP journey entry point.
 *
 * Renders one step of the journey at a time:
 *   idle               → Welcome screen with "Start FYP" button
 *   INDUSTRY_SELECTION → IndustrySelector cards
 *   BRANCH_SELECTION   → BranchSelector cards
 *   EVIDENCE_RESEARCH  → ResearchProgressCard (start, live progress, summary)
 *                        + ProblemProgressCard (finding problems, right after research)
 *   PROBLEM_OPTIONS    → ProblemOptions (3–5 ProblemOpportunityCards, confirm step)
 *   PROBLEM_SELECTED   → SelectedProblemCard
 */

import { useGreyActions, useGreyAgent, useGreyUIState } from "@/core/grey-agent";
import { BranchSelector } from "@/domains/fyp/components/BranchSelector";
import { IndustrySelector } from "@/domains/fyp/components/IndustrySelector";
import { ProblemOptions } from "@/domains/fyp/components/ProblemOptions";
import { ProblemProgressCard } from "@/domains/fyp/components/ProblemProgressCard";
import { ResearchProgressCard } from "@/domains/fyp/components/ResearchProgressCard";
import { SelectedProblemCard } from "@/domains/fyp/components/SelectedProblemCard";

// Stages whose cards show their own progress, so the generic spinner is hidden.
const STAGES_WITH_OWN_PROGRESS = ["EVIDENCE_RESEARCH", "PROBLEM_OPTIONS"];

export default function Home() {
  const state = useGreyUIState();
  const { isLoading, error } = useGreyAgent();
  const { startProject } = useGreyActions();

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Conversation area */}
      <div className="flex-1 overflow-y-auto px-6 py-8 max-w-2xl mx-auto w-full">

        {/* ── Idle — no project started ───────────────────────────────────── */}
        {state.status === "idle" && (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                Welcome to Grey
              </h1>
              <p className="mt-2 text-gray-500 text-sm">
                Grey helps you discover a real-world FYP idea, validate it with
                evidence, and generate a supervisor-ready proposal.
              </p>
            </div>
            <button
              onClick={startProject}
              disabled={isLoading}
              className="rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 transition-colors"
            >
              {isLoading ? "Starting…" : "Start my FYP"}
            </button>
          </div>
        )}

        {/* ── Loading spinner (some stages show their own progress instead) ── */}
        {isLoading && !STAGES_WITH_OWN_PROGRESS.includes(state.currentStage) && (
          <div className="flex items-center gap-2 text-sm text-gray-400 mt-4">
            <span className="animate-spin">⟳</span>
            <span>Grey is thinking…</span>
          </div>
        )}

        {/* ── Error message ───────────────────────────────────────────────── */}
        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* ── INDUSTRY_SELECTION ──────────────────────────────────────────── */}
        {state.currentStage === "INDUSTRY_SELECTION" && !isLoading && (
          <IndustrySelector />
        )}

        {/* ── BRANCH_SELECTION ────────────────────────────────────────────── */}
        {state.currentStage === "BRANCH_SELECTION" && !isLoading && (
          <BranchSelector />
        )}

        {/* ── EVIDENCE_RESEARCH: research, then finding problems ─────────── */}
        <div className="flex flex-col gap-4">
          <ResearchProgressCard />
          <ProblemProgressCard />
        </div>

        {/* ── PROBLEM_OPTIONS — the student's mandatory choice ────────────── */}
        <ProblemOptions />

        {/* ── PROBLEM_SELECTED — discovery complete (Release 0.3) ─────────── */}
        <SelectedProblemCard />

      </div>

      {/* Chat input bar — placeholder (wired up with CopilotKit in a future step) */}
      <div className="border-t border-gray-200 bg-white px-4 py-3">
        <div className="max-w-2xl mx-auto flex gap-2">
          <input
            type="text"
            placeholder="Ask Grey…"
            disabled
            className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-900 placeholder-gray-400 disabled:bg-gray-50 disabled:cursor-not-allowed"
          />
          <button
            disabled
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
