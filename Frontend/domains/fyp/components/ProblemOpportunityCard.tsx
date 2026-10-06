"use client";

/**
 * ProblemOpportunityCard — one evidence-backed problem the student can choose
 * (product blueprint §14).
 *
 * Shows the problem, why it matters, a possible FYP direction and how strong
 * its evidence is. "View sources" opens the cited evidence, so the student can
 * always see where the idea came from (blueprint §10). Links open in a new tab.
 *
 * The card doesn't save anything itself: "Choose this problem" calls `onChoose`,
 * and the parent asks the student to confirm first.
 */

import { useState } from "react";
import type { ProblemOption } from "../problems";
import { sourceTypeLabel, TASK_TYPE_LABELS } from "../problems";

const TIER_STYLE: Record<string, string> = {
  A: "bg-green-50 text-green-700 border-green-200",
  B: "bg-blue-50 text-blue-700 border-blue-200",
  C: "bg-gray-50 text-gray-600 border-gray-200",
};

export function TierBadge({ tier, count }: { tier: string; count?: number }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs font-medium ${TIER_STYLE[tier] ?? TIER_STYLE.C}`}>
      Tier {tier}
      {count !== undefined && ` × ${count}`}
    </span>
  );
}

interface ProblemOpportunityCardProps {
  problem: ProblemOption;
  onChoose: (problem: ProblemOption) => void;
  disabled?: boolean;
}

export function ProblemOpportunityCard({ problem, onChoose, disabled = false }: ProblemOpportunityCardProps) {
  const [showSources, setShowSources] = useState(false);
  const strength = problem.evidence_strength;
  const sourcesId = `sources-${problem.id}`;

  return (
    <article
      className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
      aria-label={problem.title}
    >
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="text-xs uppercase tracking-wide text-gray-400">
          {TASK_TYPE_LABELS[problem.task_type] ?? "Problem"}
        </span>
        {strength.tier_a > 0 && <TierBadge tier="A" count={strength.tier_a} />}
        {strength.tier_b > 0 && <TierBadge tier="B" count={strength.tier_b} />}
        {strength.tier_c > 0 && <TierBadge tier="C" count={strength.tier_c} />}
      </div>

      <h3 className="text-base font-semibold text-gray-900">{problem.title}</h3>

      <dl className="mt-3 flex flex-col gap-2 text-sm">
        <div>
          <dt className="font-medium text-gray-700">Real-world problem</dt>
          <dd className="text-gray-600">{problem.real_world_problem}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-700">Why it matters</dt>
          <dd className="text-gray-600">{problem.why_it_matters}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-700">Possible FYP direction</dt>
          <dd className="text-gray-600">{problem.possible_fyp_direction}</dd>
        </div>
      </dl>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onChoose(problem)}
          disabled={disabled}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Choose this problem
        </button>
        <button
          type="button"
          onClick={() => setShowSources((open) => !open)}
          aria-expanded={showSources}
          aria-controls={sourcesId}
          className="text-sm font-medium text-accent hover:underline"
        >
          {showSources ? "Hide sources" : `View sources (${problem.evidence.length})`}
        </button>
      </div>

      {showSources && (
        <div id={sourcesId} className="mt-4 border-t border-gray-100 pt-4">
          <p className="text-sm text-gray-600 mb-3">
            <span className="font-medium text-gray-700">What organizations are building: </span>
            {problem.observed_solutions}
          </p>
          <ul className="flex flex-col gap-3" aria-label="Sources">
            {problem.evidence.map((source) => (
              <li key={source.evidence_source_id || source.url} className="text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <TierBadge tier={source.evidence_tier} />
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-accent hover:underline"
                  >
                    {source.title}
                  </a>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  {sourceTypeLabel(source.source_type, source.evidence_tier)}
                  {" · "}
                  {source.organization}
                  {source.published_date && ` · ${source.published_date}`}
                </p>
                <p className="text-gray-600 mt-1">“{source.supporting_point}”</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
